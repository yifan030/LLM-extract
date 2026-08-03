# -*- coding: utf-8 -*-
"""应用级异常体系。"""


class AppError(Exception):
    """业务异常基类，由全局 exception_handler 统一处理。"""
    def __init__(self, message: str, status_code: int = 500, detail: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


class MinioObjectNotFound(AppError):
    def __init__(self, object_key: str):
        super().__init__(
            f"MinIO 文件不存在: {object_key}",
            status_code=404,
            detail={"object_key": object_key},
        )


class LlmApiCallError(AppError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, status_code=502, detail=detail)


class HugeGraphError(AppError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, status_code=502, detail=detail)


class KnowledgePointNotFound(AppError):
    def __init__(self, kp_id: str):
        super().__init__(
            f"知识点不存在: {kp_id}",
            status_code=404,
            detail={"kp_id": kp_id},
        )


class ExtractionValidationError(AppError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, status_code=422, detail=detail)
