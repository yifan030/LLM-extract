# -*- coding: utf-8 -*-
"""FastAPI 应用入口。"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from service.api.router import router as v1_router
from conf.config import Settings
from core.events import start_consumer
from core.exceptions import AppError
from logs.logging import get_logger
from libs.hugegraph import HugeGraphRepository
from libs.minio import MinioRepository
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

    # ── 启动 Redis Streams 消费者 ──
    if settings.redis_url:
        minio_repo = MinioRepository(settings)
        hg_repo = HugeGraphRepository(settings)
        llm_svc = LlmService(settings)
        prompt_svc = PromptService(hg_repo)
        matcher_svc = MatcherService()
        extraction_svc = ExtractionService(
            minio_repo, hg_repo, llm_svc, prompt_svc, matcher_svc, settings,
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
    log.info("应用关闭")


def create_app() -> FastAPI:
    app_ = FastAPI(
        title="Exam Extract API",
        description="试卷抽取与知识点关联导入服务",
        version="1.0.0",
        lifespan=lifespan,
    )

    app_.include_router(v1_router, prefix="/api/v1")

    @app_.get("/health")
    async def health():
        return {"status": "ok"}

    @app_.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": exc.detail},
        )

    @app_.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": "请求参数校验失败", "detail": exc.errors()},
        )

    @app_.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        log.exception("未处理异常")
        return JSONResponse(
            status_code=500,
            content={"error": "内部服务错误"},
        )

    return app_


app = create_app()
