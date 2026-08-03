"""MinIO 文件浏览 + webhook 端点。"""
from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_minio_service
from app.core.logging import get_logger
from app.domain.schemas import MinioFileItem
from app.services.minio import MinioService

router = APIRouter()
log = get_logger(__name__)


@router.get("/minio/files", response_model=list[MinioFileItem])
async def list_files(
    prefix: str = Query(default=""),
    limit: int = Query(default=50, le=200),
    svc: MinioService = Depends(get_minio_service),
):
    return await svc.list_files(prefix=prefix, limit=limit)


@router.post("/minio/webhook/minio")
async def minio_webhook(request: Request):
    """MinIO bucket notification 回调。"""
    body = await request.json()
    for record in body.get("Records", []):
        key = record.get("s3", {}).get("object", {}).get("key", "")
        if key.endswith(".md"):
            log.info("收到 MinIO 事件: %s", key)
    return {"ok": True}
