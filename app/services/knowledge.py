# -*- coding: utf-8 -*-
"""知识点查询服务。"""
from app.core.exceptions import KnowledgePointNotFound, PaperNotFound
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

# question_type_id → 题型名称
_TYPE_ID_TO_NAME: dict[int, str] = {1: "单选题", 2: "多选题", 3: "填空题", 4: "解答题"}


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
            raise PaperNotFound(paper_id)
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

    # ── 试卷 → 试题（完整内容）──────────────────────────────

    async def list_paper_questions(self, paper_id: str) -> list[QuestionDetail]:
        """返回试卷下所有试题的完整内容（题目、答案、知识点）。"""
        paper = await self._hg.get_vertex(paper_id)
        if paper is None:
            raise PaperNotFound(paper_id)
        paper_title = paper.get("properties", {}).get("title", "")

        edges = await self._hg.get_vertex_edges(paper_id, direction="out", label="contains")
        questions: list[QuestionDetail] = []
        for e in edges:
            q_id: str = e.get("inV", "")
            if not q_id:
                continue
            q = await self._hg.get_vertex(q_id)
            if q is None:
                continue
            props = q.get("properties", {})
            kps = await self._get_question_knowledge_points(q_id)
            questions.append(QuestionDetail(
                question_id=q_id,
                number=str(props.get("question_id", "")),
                content=props.get("content", ""),
                answer=props.get("answer"),
                score=props.get("score"),
                question_type=self._resolve_type_name(props.get("question_type_id")),
                exam_paper_id=str(props.get("exam_paper_id", "")),
                exam_paper_title=paper_title,
                knowledge_points=kps,
            ))
        return questions

    # ── 知识点 → 试题（完整内容）──────────────────────────────

    async def list_kp_questions(self, kp_id: str) -> list[QuestionDetail]:
        """返回四级知识点关联的所有试题完整内容。"""
        kp = await self._hg.get_vertex(kp_id)
        if kp is None:
            raise KnowledgePointNotFound(kp_id)

        # examines 边: question(outV) → knowledge_point(inV)
        edges = await self._hg.get_vertex_edges(kp_id, direction="in", label="examines")
        questions: list[QuestionDetail] = []
        # 缓存试卷标题，避免同一试卷重复查询
        paper_title_cache: dict[str, str] = {}
        for e in edges:
            q_id: str = e.get("outV", "")
            if not q_id:
                continue
            q = await self._hg.get_vertex(q_id)
            if q is None:
                continue
            props = q.get("properties", {})
            paper_id_prop = str(props.get("exam_paper_id", ""))
            if paper_id_prop not in paper_title_cache:
                paper_title_cache[paper_id_prop] = await self._get_paper_title_for_question(q_id)
            paper_title = paper_title_cache[paper_id_prop]
            kps = await self._get_question_knowledge_points(q_id)
            questions.append(QuestionDetail(
                question_id=q_id,
                number=str(props.get("question_id", "")),
                content=props.get("content", ""),
                answer=props.get("answer"),
                score=props.get("score"),
                question_type=self._resolve_type_name(props.get("question_type_id")),
                exam_paper_id=paper_id_prop,
                exam_paper_title=paper_title,
                knowledge_points=kps,
            ))
        return questions

    # ── 试题详情 ────────────────────────────────────────────

    async def get_question(self, question_id: str) -> QuestionDetail:
        vertex = await self._hg.get_vertex(question_id)
        if vertex is None:
            raise KnowledgePointNotFound(question_id)
        props = vertex.get("properties", {})
        paper_title = await self._get_paper_title_for_question(question_id)
        kps = await self._get_question_knowledge_points(question_id)
        return QuestionDetail(
            question_id=question_id,
            number=str(props.get("question_id", "")),
            content=props.get("content", ""),
            answer=props.get("answer"),
            score=props.get("score"),
            question_type=self._resolve_type_name(props.get("question_type_id")),
            exam_paper_id=str(props.get("exam_paper_id", "")),
            exam_paper_title=paper_title,
            knowledge_points=kps,
        )

    # ── 辅助方法 ────────────────────────────────────────────

    async def _get_question_knowledge_points(self, question_id: str) -> list[str]:
        """查试题的 examines 出边，返回关联的知识点名称列表。"""
        edges = await self._hg.get_vertex_edges(question_id, direction="out", label="examines")
        names: list[str] = []
        for e in edges:
            kp_vid: str = e.get("inV", "")
            # KP 顶点 ID 格式: "level_4_{name}"
            if kp_vid.startswith("level_4_"):
                names.append(kp_vid[len("level_4_"):])
        return names

    async def _get_paper_title_for_question(self, question_id: str) -> str:
        """查试题的 contains 入边，返回所属试卷标题。"""
        edges = await self._hg.get_vertex_edges(question_id, direction="in", label="contains")
        for e in edges:
            paper_id: str = e.get("outV", "")
            if paper_id:
                paper = await self._hg.get_vertex(paper_id)
                if paper:
                    return paper.get("properties", {}).get("title", "")
        return ""

    @staticmethod
    def _resolve_type_name(type_id: int | None) -> str:
        """将 question_type_id 整数转为题型名称。"""
        if type_id is None:
            return ""
        return _TYPE_ID_TO_NAME.get(int(type_id), str(type_id))
