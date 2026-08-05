"""向量搜索端点。"""
from fastapi import APIRouter, Depends

from model.schemas import SearchRequest, SearchResponse, SearchHit
from service.api.deps import get_embed_svc, get_milvus_repo
from service.search import SearchService
from libs.milvus import MilvusRepository
from service.embedding import EmbeddingService

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/questions", response_model=SearchResponse)
async def search_questions(
    req: SearchRequest,
    milvus_repo: MilvusRepository = Depends(get_milvus_repo),
    embed_svc: EmbeddingService | None = Depends(get_embed_svc),
):
    """按语义相似度检索试题（dense + BM25 混合搜索）。

    - ``query``: 自然语言查询文本
    - ``kp_level`` + ``kp_name``: 可选知识点标量过滤，如 ``level=2, name="集合"``
    - ``limit``: 返回条数（1-100）

    依赖未就绪（Embedding 未配置 / Milvus 未部署）时返回 503 错误。
    """
    svc = SearchService(milvus_repo, embed_svc)
    kp_filter = None
    if req.kp_level is not None and req.kp_name:
        kp_filter = {"level": req.kp_level, "name": req.kp_name}

    results = await svc.search_questions(
        query_text=req.query,
        kp_filter=kp_filter,
        limit=req.limit,
    )

    hits = [SearchHit(**hit) for hit in results]
    return SearchResponse(
        query=req.query,
        kp_filter=f"level_{req.kp_level}={req.kp_name}" if kp_filter else None,
        hits=hits,
        total=len(hits),
    )
