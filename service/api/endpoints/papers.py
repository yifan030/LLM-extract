"""试卷与题目查询端点。"""
from fastapi import APIRouter, Depends, Query

from service.api.deps import get_knowledge_service
from model.schemas import (
    PaperDetail,
    PaperSummary,
    PaginatedResponse,
    QuestionDetail,
)
from service.knowledge import KnowledgeService

router = APIRouter()


@router.get("/papers", response_model=PaginatedResponse[PaperSummary])
async def list_papers(
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0),
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.list_papers(limit=limit, offset=offset)


@router.get("/papers/{paper_id}", response_model=PaperDetail)
async def get_paper(
    paper_id: str,
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.get_paper(paper_id)


@router.get("/papers/{paper_id}/questions", response_model=list[QuestionDetail])
async def list_paper_questions(
    paper_id: str,
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.list_paper_questions(paper_id)


@router.get("/questions/{question_id}", response_model=QuestionDetail)
async def get_question(
    question_id: str,
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.get_question(question_id)
