# -*- coding: utf-8 -*-
"""Stage 2 matcher service: links LLM extraction output to level-4 knowledge points.

:meth:`MatcherService.match` is the strict exact-name matcher.
:meth:`MatcherService.match_fuzzy` adds a Milvus vector-search fallback for
candidates that do not exactly match any level-4 KP name.
"""
import hashlib
from datetime import datetime

from logs.logging import get_logger
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

log = get_logger(__name__)


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

    async def match_fuzzy(
        self,
        llm_result: LlmExtractResult,
        source_file: str,
        level4_names: list[str],
        embed_svc,           # EmbeddingService
        milvus_repo,         # MilvusRepository
        threshold: float = 0.75,
        top_k: int = 5,
    ) -> IntermediateJson:
        """Like :meth:`match`, but unmatched candidates fall back to fuzzy matching.

        For every candidate that does not exactly match a level-4 KP name, embed
        the candidate name and search ``kp_embed_v1`` for semantically similar
        level-4 KPs. A hit is accepted as a match when its cosine similarity
        (Milvus ``distance``) is ``>= threshold``.

        Unmatched candidates are recorded with a reason indicating why:

        - ``BELOW_SIM_THRESHOLD`` — search returned hits, but the top hit is
          below ``threshold``.
        - ``NO_FUZZY_MATCH`` — the search returned no hits (or the top hit was
          missing a usable ``kp_id``).
        - ``EMBED_FAILED`` — embedding the candidate raised.
        - ``SEARCH_FAILED`` — the Milvus search raised.
        """
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

            # 每题一个去重集合：同一 question-KP 只发一条 examines 边
            matched_kp_ids: set[str] = set()

            for candidate in q.candidate_knowledge_points:
                candidate = candidate.strip()
                if not candidate:
                    continue

                # Fast path: exact name match
                if candidate in level4_map:
                    kp_id = level4_map[candidate]
                    if kp_id not in matched_kp_ids:
                        edges.append(Edge(
                            label="examines",
                            outV=question_vertex_id,
                            inV=kp_id,
                            properties={"create_time": now},
                        ))
                        matched_kp_ids.add(kp_id)
                    continue

                # Fuzzy path: embed candidate → search kp_embed_v1 → accept if >= threshold
                kp_id, reason = await self._fuzzy_match_candidate(
                    candidate, embed_svc, milvus_repo, threshold, top_k
                )
                if kp_id is not None:
                    if kp_id not in matched_kp_ids:
                        edges.append(Edge(
                            label="examines",
                            outV=question_vertex_id,
                            inV=kp_id,
                            properties={"create_time": now},
                        ))
                        matched_kp_ids.add(kp_id)
                else:
                    unmatched.append(UnmatchedItem(
                        question_id=question_vertex_id,
                        number=q.number,
                        candidate=candidate,
                        reason=reason or "NO_FUZZY_MATCH",
                    ))

        return IntermediateJson(
            metadata=Metadata(
                source_file=source_file,
                generated_at=now_iso,
                matching_mode="fuzzy",
            ),
            vertices=vertices,
            edges=edges,
            unmatched=unmatched,
        )

    async def _fuzzy_match_candidate(
        self,
        candidate: str,
        embed_svc,
        milvus_repo,
        threshold: float,
        top_k: int,
    ) -> tuple[str | None, str | None]:
        """Embed ``candidate`` and search for its most similar level-4 KP.

        Returns ``(matched_kp_id, None)`` on success, or
        ``(None, reason)`` where ``reason`` is one of ``EMBED_FAILED``,
        ``SEARCH_FAILED``, ``NO_FUZZY_MATCH``, ``BELOW_SIM_THRESHOLD``.
        """
        try:
            query_vec = await embed_svc.embed_one(candidate)
        except Exception as exc:  # noqa: BLE001 - 外部服务异常，按未匹配降级
            log.warning("候选知识点 embed 失败: candidate=%s err=%s", candidate, exc)
            return None, "EMBED_FAILED"

        try:
            results = await milvus_repo.search_kps(query_vec, limit=top_k, level=4)
        except Exception as exc:  # noqa: BLE001 - 外部服务异常，按未匹配降级
            log.warning("候选知识点 Milvus 检索失败: candidate=%s err=%s", candidate, exc)
            return None, "SEARCH_FAILED"

        if not results:
            return None, "NO_FUZZY_MATCH"

        top_hit = results[0]
        distance = top_hit.get("distance", 0.0)
        if distance >= threshold:
            entity = top_hit.get("entity", {})
            kp_id = entity.get("kp_id") if isinstance(entity, dict) else None
            if kp_id:
                return kp_id, None
            log.warning(
                "检索命中的 entity 缺少 kp_id: candidate=%s hit=%s", candidate, top_hit
            )
            return None, "NO_FUZZY_MATCH"

        return None, "BELOW_SIM_THRESHOLD"

    def _build_paper_props(self, paper: ExamPaper, paper_int_id: int, now: str) -> dict:
        props = {
            "exam_paper_id": paper_int_id,
            "title": paper.title,
            "subject": paper.subject,
            "grade": paper.grade,
            "total_score": paper.total_score,
            "duration_minutes": paper.duration_minutes,
            "created_at": now,
            "updated_at": now,
        }
        return {k: v for k, v in props.items() if v is not None}

    def _build_question_props(
        self,
        q: Question,
        q_int_id: int,
        paper_int_id: int,
        question_types: list[QuestionType],
        now: str,
    ) -> dict:
        type_id = self._resolve_question_type_id(q.question_type, question_types)
        props = {
            "question_id": q_int_id,
            "number": q.number,
            "content": q.content,
            "answer": q.answer,
            "score": q.score,
            "question_type_id": type_id,
            "exam_paper_id": paper_int_id,
            "img_urls": q.img_url if q.img_url else [],
            "answer_imgs": q.answer_img if q.answer_img else [],
            "created_at": now,
            "updated_at": now,
        }
        return {k: v for k, v in props.items() if v is not None}

    def _resolve_question_type_id(self, name: str, question_types: list[QuestionType]) -> int:
        mapping = {"单选题": 1, "多选题": 2, "填空题": 3, "解答题": 4}
        return mapping.get(name, 0)
