# -*- coding: utf-8 -*-
"""FastAPI 应用入口。"""
import asyncio
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from service.api.router import router as v1_router
from conf.config import Settings
from core.events import start_consumer
from core.exceptions import AppError
from logs.context import set_correlation_id, get_correlation_id
from logs.logging import get_logger
from libs.hugegraph import HugeGraphRepository
from libs.minio import MinioRepository
from libs.milvus import MilvusRepository
from service.embedding import EmbeddingService
from service.extraction import ExtractionService
from service.llm import LlmService
from service.matcher import MatcherService
from service.prompt import PromptService

log = get_logger(__name__)

_consumer_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer_task

    settings = Settings()
    log.info("应用启动")

    # Milvus 长连接仓库（client 惰性创建）；关闭阶段需显式释放
    milvus_repo: MilvusRepository | None = None

    # ── 启动 Redis Streams 消费者 ──
    if settings.redis_url:
        minio_repo = MinioRepository(settings)
        hg_repo = HugeGraphRepository(settings)
        llm_svc = LlmService(settings)
        prompt_svc = PromptService(hg_repo)
        matcher_svc = MatcherService()
        # Milvus 双写：未配置 embedding 服务时跳过
        embed_svc = (
            EmbeddingService(settings)
            if settings.embed_base_url
            else None
        )
        milvus_repo = MilvusRepository(settings)
        # 启动时幂等建表（已存在则跳过），后续双写不再重复检查
        await milvus_repo.ensure_collections()
        # 启动自检：校验 embedding 维度与 Milvus schema 一致（失败只告警，不阻断启动）
        if embed_svc is not None:
            ok, msg = await embed_svc.check_dimension()
            log.info("Embedding dimension check: %s", msg)
            if not ok:
                log.warning("Embedding dimension MISMATCH — Milvus operations may fail")
        extraction_svc = ExtractionService(
            minio_repo, hg_repo, llm_svc, prompt_svc, matcher_svc, settings,
            embed_svc=embed_svc,
            milvus_repo=milvus_repo,
        )
        _consumer_task = asyncio.create_task(
            start_consumer(settings.redis_url, extraction_svc)
        )
        log.info("Redis Stream 消费者后台任务已创建")

    yield

    # ── 关闭 ──
    if _consumer_task:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    if milvus_repo is not None:
        await milvus_repo.close()
    log.info("应用关闭")


def create_app() -> FastAPI:
    app_ = FastAPI(
        title="Exam Extract API",
        description="试卷抽取与知识点关联导入服务",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app_.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        cid = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex[:12]
        set_correlation_id(cid)
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = cid
        return response

    app_.include_router(v1_router, prefix="/api/v1")

    @app_.get("/health")
    async def health():
        return {"status": "ok"}

    @app_.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        detail = dict(exc.detail)
        detail["correlation_id"] = get_correlation_id()
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": detail},
        )

    @app_.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": "请求参数校验失败", "detail": exc.errors()},
        )

    @app_.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        cid = get_correlation_id()
        log.exception("未处理异常 [cid=%s]", cid)
        return JSONResponse(
            status_code=500,
            content={"error": "内部服务错误", "correlation_id": cid},
            headers={"X-Correlation-Id": cid},
        )

    return app_


app = create_app()
