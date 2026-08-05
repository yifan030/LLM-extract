"""试卷判分端点 —— 接收 PDF 文件，调用 OCR 服务解析后转为判分 JSON。"""
import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile

from service.api.deps import get_scoring_service, get_settings
from conf.config import Settings
from logs.logging import get_logger
from model.schemas import ScoringResponse
from service.scoring import ScoringService

log = get_logger(__name__)

router = APIRouter()


@router.post("/scoring/parse", response_model=ScoringResponse)
async def parse_for_scoring(
    paper_id: str = Form(..., description="试卷 ID，用于从数据库查询标准答案"),
    file: UploadFile = File(..., description="要解析的 PDF 文件"),
    svc: ScoringService = Depends(get_scoring_service),
    settings: Settings = Depends(get_settings),
):
    """上传 PDF 试卷，调用 OCR 服务解析后返回判分 JSON，不经过 LLM。"""
    # 1. 将上传的文件转发给 OCR 服务
    ocr_markdown = await _call_ocr_service(file, settings.ocr_service_url)

    # 2. 用 ScoringService 解析拼接后的 markdown
    return await svc.parse(ocr_markdown, paper_id)


async def _call_ocr_service(file: UploadFile, ocr_url: str) -> str:
    """将上传的文件转发给外部 OCR 服务，返回拼接后的完整 markdown 文本。"""
    content = await file.read()

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            ocr_url,
            files={"file": (file.filename or "upload.pdf", content, file.content_type or "application/pdf")},
        )
        resp.raise_for_status()
        data = resp.json()

    # OCR 响应格式: {"request_id": "...", "status": "done", "pages": [{"page_index": 0, "markdown": "..."}, ...]}
    if data.get("status") != "done":
        raise RuntimeError(f"OCR 服务未完成解析，status={data.get('status')}")

    pages = data.get("pages", [])
    if not pages:
        raise RuntimeError("OCR 服务返回空页面")

    # 按 page_index 排序后拼接 markdown
    pages_sorted = sorted(pages, key=lambda p: p.get("page_index", 0))
    markdown_parts = [p.get("markdown", "") for p in pages_sorted]
    return "\n\n".join(markdown_parts)
