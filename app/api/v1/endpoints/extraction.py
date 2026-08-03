"""抽取流水线端点。"""
from fastapi import APIRouter, Depends

from app.api.deps import get_extraction_service
from app.domain.schemas import ExtractRequest, ExtractResult
from app.services.extraction import ExtractionService

router = APIRouter()


@router.post("/extract", response_model=ExtractResult)
async def extract(
    req: ExtractRequest,
    svc: ExtractionService = Depends(get_extraction_service),
):
    report = await svc.run(req.object_key)
    return ExtractResult(
        paper_id=report["paper_id"],
        question_count=report["question_count"],
        matched_kp=report["matched_kp"],
    )
