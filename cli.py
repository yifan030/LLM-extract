# -*- coding: utf-8 -*-
"""CLI 入口 — 复用 services 层。"""
import argparse
import asyncio

from conf.config import Settings
from libs.hugegraph import HugeGraphRepository
from libs.minio import MinioRepository
from libs.milvus import MilvusRepository
from service.embedding import EmbeddingService
from service.extraction import ExtractionService
from service.llm import LlmService
from service.matcher import MatcherService
from service.prompt import PromptService


async def main():
    parser = argparse.ArgumentParser(description="试卷抽取并导入 HugeGraph")
    parser.add_argument("--object-key", required=True, help="MinIO 文件路径")
    parser.add_argument("--save-artifacts", action="store_true", default=False, help="保存中间产物到磁盘")
    parser.add_argument("--skip-import", action="store_true", default=False, help="仅抽取+保存，不导入 HugeGraph")
    args = parser.parse_args()

    settings = Settings()
    minio_repo = MinioRepository(settings)
    hg_repo = HugeGraphRepository(settings)
    llm_svc = LlmService(settings)
    prompt_svc = PromptService(hg_repo)
    matcher_svc = MatcherService()
    # Milvus 双写：未配置 embedding 服务时跳过
    embed_svc = (
        EmbeddingService(settings)
        if settings.embed_base_url
        else None
    )
    milvus_repo = MilvusRepository(settings)
    extraction_svc = ExtractionService(
        minio_repo, hg_repo, llm_svc, prompt_svc, matcher_svc, settings,
        embed_svc=embed_svc,
        milvus_repo=milvus_repo,
    )

    report = await extraction_svc.run(
        args.object_key,
        save_artifacts=args.save_artifacts,
        import_to_hg=not args.skip_import,
    )
    print(
        f"完成: paper_id={report['paper_id']}, "
        f"questions={report['question_count']}, "
        f"matched_kp={report['matched_kp']}"
    )
    if report.get("unmatched_count"):
        print(f"未匹配知识点: {report['unmatched_count']}")
    if report.get("artifact_dir"):
        print(f"产物目录: {report['artifact_dir']}")


if __name__ == "__main__":
    asyncio.run(main())
