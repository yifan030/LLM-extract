# -*- coding: utf-8 -*-
"""MySQL 独立导入 API 端点。"""
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from model.mysql_schemas import (
    PaperImportRequest,
    PaperImportResponse,
    AnswerImportRequest,
    AnswerImportResponse,
    AnswerSheetImportRequest,
    AnswerSheetImportResponse,
    CsvExportRequest,
    RecommendRequest,
    RecommendResponse,
    BatchImportResponse,
    BatchImportStatusResponse,
)
from service.api.deps import get_mysql_import_service
from service.mysql_import import MySqlImportService

router = APIRouter(prefix="/mysql")


@router.post("/import/paper", response_model=PaperImportResponse, tags=["mysql"])
async def import_paper(
    req: PaperImportRequest,
    svc: MySqlImportService = Depends(get_mysql_import_service),
):
    """从 MinIO 读取试卷 Markdown，LLM 抽取后写入 MySQL。"""
    return await svc.import_paper(req.object_key)


@router.post("/import/answers", response_model=AnswerImportResponse, tags=["mysql"])
async def import_answers(
    req: AnswerImportRequest,
    svc: MySqlImportService = Depends(get_mysql_import_service),
):
    """从 MinIO 读取标准答案 Markdown，解析后更新已有题目的 answer 字段。"""
    return await svc.import_answers(req.object_key, req.paper_id)


@router.post(
    "/import/answer-sheet",
    response_model=AnswerSheetImportResponse,
    tags=["mysql"],
)
async def import_answer_sheet(
    req: AnswerSheetImportRequest,
    svc: MySqlImportService = Depends(get_mysql_import_service),
):
    """从 MinIO 读取答题卡图片，OCR 识别学生信息和各题得分后写入 MySQL。"""
    return await svc.import_answer_sheet(req.object_key, req.paper_id)


@router.post("/export/csv", tags=["mysql"])
async def export_csv(
    req: CsvExportRequest,
    svc: MySqlImportService = Depends(get_mysql_import_service),
):
    """导出指定表为 CSV，打包为 ZIP 返回。"""
    zip_path = await svc.export_csv(req.tables, req.paper_id)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename="mysql_export.zip",
    )


@router.post("/recommend/weak-kp", response_model=RecommendResponse, tags=["mysql"])
async def recommend_weak_kp(
    req: RecommendRequest,
    svc: MySqlImportService = Depends(get_mysql_import_service),
):
    """查找薄弱知识点（正确率 < threshold）并推荐同类题。"""
    return await svc.get_weak_kp_recommend(
        req.student_id, req.exam_paper_id, req.accuracy_threshold
    )


@router.post("/import/batch", response_model=BatchImportResponse, tags=["mysql"])
async def import_batch(
    svc: MySqlImportService = Depends(get_mysql_import_service),
):
    """一键批量增量导入：列出 MinIO 桶内全部 .md，跳过已入库，后台导入。"""
    return await svc.start_batch_import()


@router.get(
    "/import/batch/{job_id}",
    response_model=BatchImportStatusResponse,
    tags=["mysql"],
)
async def import_batch_status(
    job_id: str,
    svc: MySqlImportService = Depends(get_mysql_import_service),
):
    """轮询批量导入进度。"""
    return svc.get_batch_status(job_id)
