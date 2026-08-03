# -*- coding: utf-8 -*-
"""Stage 2 strict matcher: links LLM extraction output to level-4 knowledge points."""
from datetime import datetime
from typing import List, Optional

from exam_extract.models import (
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
from exam_extract.snowflake import Snowflake


class Matcher:
    def __init__(self, level4_names: List[str], snowflake: Optional[Snowflake] = None):
        self.level4_map = {name.strip(): f"level_4_{name.strip()}" for name in level4_names}
        self.snowflake = snowflake or Snowflake()

    def match(self, llm_result: LlmExtractResult, source_file: str) -> IntermediateJson:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_iso = datetime.now().isoformat()

        exam_paper_id = self.snowflake.next_id()
        paper_vertex_id = f"paper_{exam_paper_id}"

        vertices: List[Vertex] = []
        edges: List[Edge] = []
        unmatched: List[UnmatchedItem] = []

        paper_props = self._build_paper_props(llm_result.exam_paper, exam_paper_id, now)
        vertices.append(Vertex(label="exam_paper", id=paper_vertex_id, properties=paper_props))

        for q in llm_result.questions:
            question_id = self.snowflake.next_id()
            question_vertex_id = f"question_{question_id}"
            question_props = self._build_question_props(
                q, question_id, exam_paper_id, llm_result.question_types, now
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
                if candidate in self.level4_map:
                    edges.append(Edge(
                        label="examines",
                        outV=question_vertex_id,
                        inV=self.level4_map[candidate],
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

    def _build_paper_props(self, paper: ExamPaper, exam_paper_id: int, now: str) -> dict:
        return {
            "exam_paper_id": exam_paper_id,
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
        question_id: int,
        exam_paper_id: int,
        question_types: List[QuestionType],
        now: str,
    ) -> dict:
        type_id = self._resolve_question_type_id(q.question_type, question_types)
        return {
            "question_id": question_id,
            "content": q.content,
            "answer": q.answer,
            "score": q.score,
            "question_type_id": type_id,
            "exam_paper_id": exam_paper_id,
            "source_file_id": 0,
            "sub_file_id": 0,
            "created_at": now,
            "updated_at": now,
        }

    def _resolve_question_type_id(self, name: str, question_types: List[QuestionType]) -> int:
        mapping = {"单选题": 1, "多选题": 2, "填空题": 3, "解答题": 4}
        return mapping.get(name, 0)
