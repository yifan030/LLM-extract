"""V1 路由汇总。"""
from fastapi import APIRouter

from app.api.v1.endpoints import extraction, knowledge, minio, papers, scoring

router = APIRouter()
router.include_router(extraction.router, tags=["extraction"])
router.include_router(minio.router, tags=["minio"])
router.include_router(knowledge.router, tags=["knowledge"])
router.include_router(papers.router, tags=["papers"])
router.include_router(scoring.router, tags=["scoring"])
