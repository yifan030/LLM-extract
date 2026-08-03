# -*- coding: utf-8 -*-
"""抽取流水线编排服务。"""
from app.core.logging import get_logger
from app.repositories.hugegraph import HugeGraphRepository
from app.repositories.minio import MinioRepository
from app.services.llm import LlmService
from app.services.matcher import MatcherService
from app.services.prompt import PromptService

log = get_logger(__name__)


class ExtractionService:
    def __init__(
        self,
        minio_repo: MinioRepository,
        hg_repo: HugeGraphRepository,
        llm_svc: LlmService,
        prompt_svc: PromptService,
        matcher_svc: MatcherService,
    ):
        self._minio = minio_repo
        self._hg = hg_repo
        self._llm = llm_svc
        self._prompt = prompt_svc
        self._matcher = matcher_svc

    async def run(self, object_key: str) -> dict:
        log.info("开始抽取流水线: object_key=%s", object_key)
        # 1. 从 MinIO 读取 Markdown
        markdown = await self._minio.get_object_text(object_key)
        # 2. 加载四级知识点名称
        level4_names = await self._hg.load_level4_names()
        # 3. 构建 Prompt
        prompt = await self._prompt.build_prompt(markdown)
        # 4. LLM 抽取
        extracted = await self._llm.extract(prompt)
        # 5. 知识点匹配 (stateless matcher: level4_names passed as arg)
        intermediate = self._matcher.match(
            extracted, source_file=object_key, level4_names=level4_names
        )
        # 6. 导入 HugeGraph
        report = await self._import_to_hg(intermediate)
        log.info("抽取完成: paper_id=%s", report["paper_id"])
        return report

    async def _import_to_hg(self, data) -> dict:
        question_type_cache = await self._hg.preload_question_types()

        vertices_created = 0
        vertices_duplicated = 0
        for v in data.vertices:
            created, dup = await self._hg.create_vertex(v)
            if created:
                vertices_created += 1
            if dup:
                vertices_duplicated += 1

        edges_created = 0
        edges_failed = 0
        for e in data.edges:
            inV = e.inV
            if e.label == "belongs_to_type":
                inV = question_type_cache.get(e.inV)
                if not inV:
                    log.error("题型顶点不存在: %s", e.inV)
                    edges_failed += 1
                    continue
                e.inV = inV
            ok = await self._hg.create_edge(e)
            if ok:
                edges_created += 1
            else:
                edges_failed += 1

        paper_v = data.vertices[0] if data.vertices else None
        paper_id = paper_v.id if paper_v else "unknown"
        return {
            "paper_id": paper_id,
            "question_count": len(data.vertices) - 1 if data.vertices else 0,
            "matched_kp": len([e for e in data.edges if e.label == "examines"]),
            "vertices_created": vertices_created,
            "vertices_duplicated": vertices_duplicated,
            "edges_created": edges_created,
            "edges_failed": edges_failed,
        }
