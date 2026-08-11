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


class PaperNotFound(AppError):
    def __init__(self, paper_id: str):
        super().__init__(
            f"试卷不存在: {paper_id}",
            status_code=404,
            detail={"paper_id": paper_id},
        )


class ExtractionValidationError(AppError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, status_code=422, detail=detail)


class SearchServiceError(AppError):
    """向量搜索服务错误（Milvus 不可用 / Embedding 未配置或调用失败）。

    使用 503 表示依赖的外部服务当前不可用，由全局 exception_handler 返回 JSON。
    """
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, status_code=503, detail=detail)


class ExternalServiceError(AppError):
    """外部服务调用失败（超时/连接拒绝/DNS 解析失败等）。"""
    def __init__(self, service: str, message: str, detail: dict | None = None):
        d = dict(detail or {})
        d["service"] = service
        super().__init__(message, status_code=502, detail=d)


class HugeGraphTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("hugegraph", message, detail)


class MilvusTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("milvus", message, detail)


class MinioTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("minio", message, detail)


class OcrServiceError(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("ocr", message, detail)


class RedisTimeout(ExternalServiceError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__("redis", message, detail)


class MySqlError(AppError):
    """MySQL 操作失败（连接超时 / 查询错误 / 约束冲突）。"""
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, status_code=502, detail=detail)
