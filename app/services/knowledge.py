# -*- coding: utf-8 -*-
"""知识点查询服务。"""
from app.core.exceptions import KnowledgePointNotFound
from app.core.logging import get_logger
from app.domain.schemas import (
    KnowledgePointDetail,
    KnowledgePointItem,
    PaginatedResponse,
    PaperDetail,
    PaperSummary,
    QuestionDetail,
    QuestionSummary,
)
from app.repositories.hugegraph import HugeGraphRepository

log = get_logger(__name__)


class KnowledgeService:
    def __init__(self, hg_repo: HugeGraphRepository):
        self._hg = hg_repo

    async def list_knowledge(
        self, level: int | None = None, limit: int = 100, offset: int = 0
    ) -> PaginatedResponse[KnowledgePointItem]:
        vertices = await self._hg.list_vertices("knowledge_point", limit=limit, offset=offset)
        items = []
        for v in vertices:
            props = v.get("properties", {})
            lv = props.get("level")
            if level is not None and lv != level:
                continue
            items.append(KnowledgePointItem(
                kp_id=v.get("id", ""),
                name=props.get("name", ""),
                level=lv,
                subject=props.get("subject"),
            ))
        return PaginatedResponse(items=items, total=len(items), limit=limit, offset=offset)

    async def get_knowledge(self, kp_id: str) -> KnowledgePointDetail:
        vertex = await self._hg.get_vertex(kp_id)
        if vertex is None:
            raise KnowledgePointNotFound(kp_id)
        props = vertex.get("properties", {})
        return KnowledgePointDetail(
            kp_id=kp_id,
            name=props.get("name", ""),
            level=props.get("level"),
            subject=props.get("subject"),
            description=props.get("description"),
            related_questions=[],
        )

    async def list_papers(self, limit: int = 100, offset: int = 0) -> PaginatedResponse[PaperSummary]:
        vertices = await self._hg.list_vertices("exam_paper", limit=limit, offset=offset)
        items = []
        for v in vertices:
            props = v.get("properties", {})
            items.append(PaperSummary(
                paper_id=v.get("id", ""),
                title=props.get("title", ""),
                subject=props.get("subject", ""),
                grade=props.get("grade"),
                question_count=0,
            ))
        return PaginatedResponse(items=items, total=len(items), limit=limit, offset=offset)

    async def get_paper(self, paper_id: str) -> PaperDetail:
        vertex = await self._hg.get_vertex(paper_id)
        if vertex is None:
            raise KnowledgePointNotFound(paper_id)
        props = vertex.get("properties", {})
        return PaperDetail(
            paper_id=paper_id,
            title=props.get("title", ""),
            subject=props.get("subject", ""),
            grade=props.get("grade"),
            total_score=props.get("total_score"),
            duration_minutes=props.get("duration_minutes"),
            questions=[],
        )

    async def list_paper_questions(self, paper_id: str) -> list:
        edges = await self._hg.get_vertex_edges(paper_id, direction="out", label="contains")
        return [{"question_id": e.get("inV")} for e in edges]

    async def get_question(self, question_id: str) -> QuestionDetail:
        vertex = await self._hg.get_vertex(question_id)
        if vertex is None:
            raise KnowledgePointNotFound(question_id)
        props = vertex.get("properties", {})
        return QuestionDetail(
            question_id=question_id,
            number=str(props.get("question_id", "")),
            content=props.get("content", ""),
            answer=props.get("answer"),
            score=props.get("score"),
            question_type="",
            exam_paper_id=str(props.get("exam_paper_id", "")),
            exam_paper_title="",
            knowledge_points=[],
        )
