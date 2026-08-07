# -*- coding: utf-8 -*-
"""FastAPI 依赖注入。"""
from functools import lru_cache

import redis.asyncio as redis
from fastapi import Depends

from conf.config import Settings
from libs.hugegraph import HugeGraphRepository
from libs.minio import MinioRepository
from libs.milvus import MilvusRepository
from service.embedding import EmbeddingService
from service.extraction import ExtractionService
from service.knowledge import KnowledgeService
from service.llm import LlmService
from service.matcher import MatcherService
from service.minio import MinioService
from service.prompt import PromptService
from service.scoring import ScoringService


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


_milvus_repo: MilvusRepository | None = None
_embed_svc: EmbeddingService | None = None
_embed_svc_sentinel = object()


def get_milvus_repo(settings: Settings = Depends(get_settings)) -> MilvusRepository:
    """Milvus 长连接仓库（进程级单例，client 惰性创建）。"""
    global _milvus_repo
    if _milvus_repo is None:
        _milvus_repo = MilvusRepository(settings)
    return _milvus_repo


def get_embed_svc(
    settings: Settings = Depends(get_settings),
) -> EmbeddingService | None:
    """Embedding 服务（进程级单例）；未配置服务地址时返回 None。"""
    global _embed_svc
    if _embed_svc is _embed_svc_sentinel:
        return None
    if _embed_svc is None:
        if not settings.embed_base_url:
            _embed_svc = _embed_svc_sentinel
            return None
        _embed_svc = EmbeddingService(settings)
    return _embed_svc


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
    embed_svc: EmbeddingService | None = Depends(get_embed_svc),
    milvus_repo: MilvusRepository | None = Depends(get_milvus_repo),
) -> ExtractionService:
    return ExtractionService(
        minio_repo, hg_repo, llm_svc, prompt_svc, matcher_svc, settings,
        embed_svc=embed_svc,
        milvus_repo=milvus_repo,
    )


def get_redis(settings: Settings = Depends(get_settings)) -> redis.Redis:
    return redis.from_url(settings.redis_url)


def get_scoring_service(
    hg_repo: HugeGraphRepository = Depends(get_hg_repo),
) -> ScoringService:
    return ScoringService(hg_repo)
