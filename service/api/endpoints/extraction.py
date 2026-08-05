"""抽取流水线端点。"""
from fastapi import APIRouter, Depends

from service.api.deps import get_extraction_service
from model.schemas import ExtractRequest, ExtractResult
from service.extraction import ExtractionService

router = APIRouter()


@router.post("/extract", response_model=ExtractResult)
async def extract(
    req: ExtractRequest,
    svc: ExtractionService = Depends(get_extraction_service),
):
    report = await svc.run(
        req.object_key,
        save_artifacts=req.save_artifacts,
        import_to_hg=req.import_to_hg,
    )
    return ExtractResult(
        paper_id=report["paper_id"],
        question_count=report["question_count"],
        matched_kp=report["matched_kp"],
        unmatched_count=report.get("unmatched_count", 0),
        artifact_dir=report.get("artifact_dir"),
        imported=report.get("imported", False),
    )
