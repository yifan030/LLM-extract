# -*- coding: utf-8 -*-
"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.v1.router import router as v1_router
from app.core.exceptions import AppError
from app.core.logging import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("应用启动")
    yield
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
