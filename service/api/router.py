"""V1 路由汇总。"""
from fastapi import APIRouter

from service.api.endpoints import (
    extraction,
    knowledge,
    minio,
    mysql_import,
    papers,
    scoring,
    search,
)

router = APIRouter()
router.include_router(extraction.router, tags=["extraction"])
router.include_router(minio.router, tags=["minio"])
router.include_router(knowledge.router, tags=["knowledge"])
router.include_router(papers.router, tags=["papers"])
router.include_router(scoring.router, tags=["scoring"])
router.include_router(search.router)
router.include_router(mysql_import.router, tags=["mysql"])
