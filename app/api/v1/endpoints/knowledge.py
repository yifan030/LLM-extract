"""知识点查询端点。"""
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_knowledge_service
from app.domain.schemas import (
    KnowledgePointDetail,
    KnowledgePointItem,
    PaginatedResponse,
    QuestionDetail,
)
from app.services.knowledge import KnowledgeService

router = APIRouter()


@router.get("/knowledge", response_model=PaginatedResponse[KnowledgePointItem])
async def list_knowledge(
    level: int | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0),
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.list_knowledge(level=level, limit=limit, offset=offset)


@router.get("/knowledge/{kp_id}", response_model=KnowledgePointDetail)
async def get_knowledge(
    kp_id: str,
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.get_knowledge(kp_id)


@router.get("/knowledge/{kp_id}/questions", response_model=list[QuestionDetail])
async def list_knowledge_questions(
    kp_id: str,
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.list_kp_questions(kp_id)
