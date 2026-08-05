# -*- coding: utf-8 -*-
"""知识点查询服务。"""
from app.core.exceptions import KnowledgePointNotFound, PaperNotFound
from app.core.logging import get_logger
from app.domain.schemas import (
    KnowledgePointDetail,
    KnowledgePointItem,
    KnowledgePointRelationsResponse,
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

    async def get_kp_relations(
        self, kp_id: str | None = None, name: str | None = None
    ) -> KnowledgePointRelationsResponse:
        """查询四级知识点的关系网络。

        返回：
        - related: 与此知识点具有 ``related_kp`` 边的四级知识点
        - ancestors: 沿 ``contains_kp`` 边向上追溯的一级/二级/三级知识点
        """
        # ── 1. 解析目标知识点 ──
        if kp_id:
            vertex = await self._hg.get_vertex(kp_id)
        elif name:
            kp_id = f"level_4_{name}"
            vertex = await self._hg.get_vertex(kp_id)
        else:
            raise ValueError("必须提供 kp_id 或 name")

        if vertex is None:
            raise KnowledgePointNotFound(kp_id or name)

        props = vertex.get("properties", {})
        kp_name = props.get("name", "")
        kp_level = props.get("level")

        # ── 2. 查找相关知识点（related_kp 双向遍历，仅保留四级）──
        related: list[KnowledgePointItem] = []
        seen_related: set[str] = set()

        # 出边：当前 KP → related_kp → 其他 KP
        out_edges = await self._hg.get_vertex_edges(kp_id, direction="out", label="related_kp")
        for e in out_edges:
            target_id: str = e.get("inV", "")
            if target_id and target_id not in seen_related:
                seen_related.add(target_id)
                target = await self._hg.get_vertex(target_id)
                if target and target.get("properties", {}).get("level") == 4:
                    tp = target.get("properties", {})
                    related.append(KnowledgePointItem(
                        kp_id=target_id,
                        name=tp.get("name", ""),
                        level=4,
                        subject=tp.get("subject"),
                    ))

        # 入边：其他 KP → related_kp → 当前 KP
        in_edges = await self._hg.get_vertex_edges(kp_id, direction="in", label="related_kp")
        for e in in_edges:
            source_id: str = e.get("outV", "")
            if source_id and source_id not in seen_related:
                seen_related.add(source_id)
                source = await self._hg.get_vertex(source_id)
                if source and source.get("properties", {}).get("level") == 4:
                    sp = source.get("properties", {})
                    related.append(KnowledgePointItem(
                        kp_id=source_id,
                        name=sp.get("name", ""),
                        level=4,
                        subject=sp.get("subject"),
                    ))

        # ── 3. 查找祖先知识点（沿 contains_kp 入边向上追溯）──
        ancestors: list[KnowledgePointItem] = []
        seen_ancestors: set[str] = set()
        current_id = kp_id

        # 向上遍历直到找不到父节点（最多 3 层：四级→三级→二级→一级）
        for _ in range(3):
            parent_edges = await self._hg.get_vertex_edges(
                current_id, direction="in", label="contains_kp"
            )
            if not parent_edges:
                break
            # 取第一个父节点继续向上（树形层级结构，每个节点只有一个直接父节点）
            parent_id: str = parent_edges[0].get("outV", "")
            if not parent_id or parent_id in seen_ancestors:
                break
            seen_ancestors.add(parent_id)
            parent = await self._hg.get_vertex(parent_id)
            if parent is None:
                break
            pp = parent.get("properties", {})
            parent_level = pp.get("level")
            if parent_level in (1, 2, 3):
                ancestors.append(KnowledgePointItem(
                    kp_id=parent_id,
                    name=pp.get("name", ""),
                    level=parent_level,
                    subject=pp.get("subject"),
                ))
            current_id = parent_id

        return KnowledgePointRelationsResponse(
            kp_id=kp_id,
            name=kp_name,
            level=kp_level,
            related=related,
            ancestors=ancestors,
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
                number=props.get("number") or str(props.get("question_id", "")),
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
                number=props.get("number") or str(props.get("question_id", "")),
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
