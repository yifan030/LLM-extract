# -*- coding: utf-8 -*-
"""FastAPI 依赖注入。"""
from functools import lru_cache

from fastapi import Depends

from app.core.config import Settings
from app.repositories.hugegraph import HugeGraphRepository
from app.repositories.minio import MinioRepository
from app.services.extraction import ExtractionService
from app.services.knowledge import KnowledgeService
from app.services.llm import LlmService
from app.services.matcher import MatcherService
from app.services.minio import MinioService
from app.services.prompt import PromptService


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_minio_repo(settings: Settings = Depends(get_settings)) -> MinioRepository:
    return MinioRepository(settings)


def get_hg_repo(settings: Settings = Depends(get_settings)) -> HugeGraphRepository:
    return HugeGraphRepository(settings)


def get_llm_service(settings: Settings = Depends(get_settings)) -> LlmService:
    return LlmService(settings)


def get_prompt_service(
    hg_repo: HugeGraphRepository = Depends(get_hg_repo),
) -> PromptService:
    return PromptService(hg_repo)


def get_matcher_service() -> MatcherService:
    return MatcherService()


def get_minio_service(
    minio_repo: MinioRepository = Depends(get_minio_repo),
) -> MinioService:
    return MinioService(minio_repo)


def get_knowledge_service(
    hg_repo: HugeGraphRepository = Depends(get_hg_repo),
) -> KnowledgeService:
    return KnowledgeService(hg_repo)


def get_extraction_service(
    minio_repo: MinioRepository = Depends(get_minio_repo),
    hg_repo: HugeGraphRepository = Depends(get_hg_repo),
    llm_svc: LlmService = Depends(get_llm_service),
    prompt_svc: PromptService = Depends(get_prompt_service),
    matcher_svc: MatcherService = Depends(get_matcher_service),
    settings: Settings = Depends(get_settings),
) -> ExtractionService:
    return ExtractionService(minio_repo, hg_repo, llm_svc, prompt_svc, matcher_svc, settings)
