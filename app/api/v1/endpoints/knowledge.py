"""知识点查询端点。"""
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_knowledge_service
from app.domain.schemas import (
    KnowledgePointDetail,
    KnowledgePointItem,
    KnowledgePointRelationsResponse,
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


# NOTE: 固定路径 /knowledge/relations/by-name 必须注册在 /knowledge/{kp_id} 之前，
# 否则 "relations" 会被路径参数捕获。
@router.get("/knowledge/relations/by-name", response_model=KnowledgePointRelationsResponse)
async def get_knowledge_relations_by_name(
    name: str = Query(..., description="四级知识点名称"),
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    """通过知识点名称查询关系网络（相关四级知识点 + 祖先知识点）。"""
    return await svc.get_kp_relations(name=name)


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


@router.get("/knowledge/{kp_id}/relations", response_model=KnowledgePointRelationsResponse)
async def get_knowledge_relations_by_id(
    kp_id: str,
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    """通过知识点 ID 查询关系网络（相关四级知识点 + 祖先知识点）。"""
    return await svc.get_kp_relations(kp_id=kp_id)
