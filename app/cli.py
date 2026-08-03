# -*- coding: utf-8 -*-
"""CLI 入口 — 复用 services 层。"""
import argparse
import asyncio

from app.core.config import Settings
from app.repositories.hugegraph import HugeGraphRepository
from app.repositories.minio import MinioRepository
from app.services.extraction import ExtractionService
from app.services.llm import LlmService
from app.services.matcher import MatcherService
from app.services.prompt import PromptService


async def main():
    parser = argparse.ArgumentParser(description="试卷抽取并导入 HugeGraph")
    parser.add_argument("--object-key", required=True, help="MinIO 文件路径")
    args = parser.parse_args()

    settings = Settings()
    minio_repo = MinioRepository(settings)
    hg_repo = HugeGraphRepository(settings)
    llm_svc = LlmService(settings)
    prompt_svc = PromptService(hg_repo)
    matcher_svc = MatcherService()
    extraction_svc = ExtractionService(minio_repo, hg_repo, llm_svc, prompt_svc, matcher_svc)

    report = await extraction_svc.run(args.object_key)
    print(
        f"完成: paper_id={report['paper_id']}, "
        f"questions={report['question_count']}, "
        f"matched_kp={report['matched_kp']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
