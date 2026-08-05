# -*- coding: utf-8 -*-
"""Stage 2 strict matcher service: links LLM extraction output to level-4 knowledge points."""
import hashlib
from datetime import datetime

from model.models import (
    Edge,
    ExamPaper,
    IntermediateJson,
    LlmExtractResult,
    Metadata,
    Question,
    QuestionType,
    UnmatchedItem,
    Vertex,
)


class MatcherService:
    """Stateless strict matcher — uses deterministic IDs for idempotent imports.

    Paper and question vertex IDs are derived from ``hashlib.md5(source_file)``
    so that re-extracting the same MinIO object always produces the same IDs.
    HugeGraph rejects duplicate vertex IDs, making re-imports safe.

    ``level4_names`` is passed to :meth:`match` rather than stored at init, so a
    single service instance can be reused across extractions with different
    knowledge-point data.
    """

    def match(
        self,
        llm_result: LlmExtractResult,
        source_file: str,
        level4_names: list[str],
    ) -> IntermediateJson:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_iso = datetime.now().isoformat()

        level4_map = {name.strip(): f"level_4_{name.strip()}" for name in level4_names}

        # deterministic paper ID from source path → 幂等导入
        paper_hash = hashlib.md5(source_file.encode()).hexdigest()
        paper_int_id = int(paper_hash[:15], 16)  # 60-bit → fits Java Long
        paper_vertex_id = f"paper_{paper_hash}"

        vertices: list[Vertex] = []
        edges: list[Edge] = []
        unmatched: list[UnmatchedItem] = []

        paper_props = self._build_paper_props(llm_result.exam_paper, paper_int_id, now)
        vertices.append(Vertex(label="exam_paper", id=paper_vertex_id, properties=paper_props))

        for q in llm_result.questions:
            # deterministic question ID from source + number → 幂等导入
            q_hash = hashlib.md5(f"{source_file}:{q.number}".encode()).hexdigest()
            q_int_id = int(q_hash[:15], 16)  # 60-bit → fits Java Long
            question_vertex_id = f"question_{q_hash}"
            question_props = self._build_question_props(
                q, q_int_id, paper_int_id, llm_result.question_types, now
            )
            vertices.append(Vertex(label="question", id=question_vertex_id, properties=question_props))

            edges.append(Edge(
                label="contains",
                outV=paper_vertex_id,
                inV=question_vertex_id,
                properties={"create_time": now},
            ))

            edges.append(Edge(
                label="belongs_to_type",
                outV=question_vertex_id,
                inV=q.question_type,  # 注意：这里先用 name，adapter 再查物理 id
                properties={"create_time": now},
            ))

            for candidate in q.candidate_knowledge_points:
                candidate = candidate.strip()
                if candidate in level4_map:
                    edges.append(Edge(
                        label="examines",
                        outV=question_vertex_id,
                        inV=level4_map[candidate],
                        properties={"create_time": now},
                    ))
                else:
                    unmatched.append(UnmatchedItem(
                        question_id=question_vertex_id,
                        number=q.number,
                        candidate=candidate,
                    ))

        return IntermediateJson(
            metadata=Metadata(
                source_file=source_file,
                generated_at=now_iso,
                matching_mode="strict",
            ),
            vertices=vertices,
            edges=edges,
            unmatched=unmatched,
        )

    def _build_paper_props(self, paper: ExamPaper, paper_int_id: int, now: str) -> dict:
        return {
            "exam_paper_id": paper_int_id,
            "title": paper.title,
            "subject": paper.subject,
            "grade": paper.grade,
            "total_score": paper.total_score,
            "duration_minutes": paper.duration_minutes,
            "created_at": now,
            "updated_at": now,
        }

    def _build_question_props(
        self,
        q: Question,
        q_int_id: int,
        paper_int_id: int,
        question_types: list[QuestionType],
        now: str,
    ) -> dict:
        type_id = self._resolve_question_type_id(q.question_type, question_types)
        return {
            "question_id": q_int_id,
            "number": q.number,
            "content": q.content,
            "answer": q.answer,
            "score": q.score,
            "question_type_id": type_id,
            "exam_paper_id": paper_int_id,
            "created_at": now,
            "updated_at": now,
        }

    def _resolve_question_type_id(self, name: str, question_types: list[QuestionType]) -> int:
        mapping = {"单选题": 1, "多选题": 2, "填空题": 3, "解答题": 4}
        return mapping.get(name, 0)
