# MySQL 批量增量导入 API 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一键批量增量导入接口——列出 `llm-construct` 桶内全部 `.md` 文件，跳过已入库的，后台逐个复用 `import_paper` 导入 MySQL，并提供状态轮询。

**Architecture:** 在现有 `MySqlImportService` 上新增 `start_batch_import`（async，前置列桶+过滤后起 `asyncio.create_task` 后台任务）、`_run_batch`（顺序导入，单文件失败不中断）、`get_batch_status`（读进程内 `dict` 注册表）。端点层新增两个薄路由。不引入答案配对逻辑（答案内嵌，`import_paper` 的 LLM 抽取已处理）。

**Tech Stack:** Python 3.10+ / FastAPI / SQLAlchemy 2.0 async / Pydantic v2 / pytest + pytest-asyncio。

## Global Constraints

- 目标桶 = `settings.minio_bucket`（当前 `.env` = `llm-construct`），**不加** prefix 过滤、**不加** bucket 覆盖参数。
- 增量判定 = `gen_paper_id(object_key)` 是否已存在于 `exam_papers` 表（`SELECT id FROM exam_papers` 一次取全）。
- 复用现有 `MySqlImportService.import_paper(object_key)`，不新增答案/试卷配对逻辑。
- 后台**顺序**执行（不并发），单个文件失败记录后继续，不中断整批。
- job 状态存进程内模块级 `dict`，job_id 用 `uuid.uuid4().hex`。
- 命名/文案全部中文，与现有日志风格一致（`log.info("...")`）。

---

### Task 1: 批量导入 DTO + 服务逻辑

**Files:**
- Modify: `model/mysql_schemas.py`（末尾追加 3 个 DTO）
- Modify: `service/mysql_import.py`（新增 `asyncio`/`uuid` import、`AppError` import、3 个方法 + 模块级注册表）
- Test: `tests/unit/test_service/test_mysql_import.py`（追加 3 个用例 + import）

**Interfaces:**
- Consumes:
  - `MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)`（已存在）
  - `MinioRepository.list_md_files(prefix, limit)`（已存在）
  - `MySqlRepository._execute(sql, params)`（已存在）
  - `import_paper(object_key) -> PaperImportResponse`（已存在，本任务复用）
  - `gen_paper_id(object_key)`（`libs/id_gen.py`，已存在）
- Produces:
  - `BatchImportResponse { job_id: str, total: int, skipped: int, status: str = "running" }`
  - `BatchFileResult { object_key: str, paper_id: str, status: str, error: str | None = None }`
  - `BatchImportStatusResponse { job_id, status, total, succeeded, failed, skipped, finished, results: list[BatchFileResult] }`
  - `async MySqlImportService.start_batch_import() -> BatchImportResponse`
  - `async MySqlImportService._run_batch(job_id: str, object_keys: list[str]) -> None`
  - `MySqlImportService.get_batch_status(job_id: str) -> BatchImportStatusResponse`
  - 模块级 `_batch_jobs: dict[str, dict]`（测试用它 `await _batch_jobs[job_id]["task"]`）

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_service/test_mysql_import.py` 顶部 import 区新增两行：

```python
from core.exceptions import AppError
from model.schemas import MinioFileItem
from service import mysql_import  # 模块级 _batch_jobs 注册表
```

文件末尾（`TestMySqlImportService` 类内，最后一个方法之后）追加 3 个用例：

```python
    async def test_start_batch_import_skips_existing(self, mock_deps):
        """批量增量导入：已入库的 paper_id 被跳过，仅导入未入库文件。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        mysql_import._batch_jobs.clear()
        minio_repo.list_md_files.return_value = [
            MinioFileItem(object_key="papers/a.md", size=1, last_modified=""),
            MinioFileItem(object_key="papers/b.md", size=1, last_modified=""),
            MinioFileItem(object_key="papers/c.md", size=1, last_modified=""),
        ]
        # exam_papers 已存在 a、b
        mysql_repo._execute.return_value = [
            {"id": gen_paper_id("papers/a.md")},
            {"id": gen_paper_id("papers/b.md")},
        ]
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)
        svc.import_paper = AsyncMock(return_value=PaperImportResponse(
            paper_id=gen_paper_id("papers/c.md"), title="", question_count=0,
        ))

        resp = await svc.start_batch_import()
        await mysql_import._batch_jobs[resp.job_id]["task"]

        assert resp.total == 3
        assert resp.skipped == 2
        assert resp.status == "running"

        status = svc.get_batch_status(resp.job_id)
        assert status.total == 3
        assert status.skipped == 2
        assert status.succeeded == 1
        assert status.failed == 0
        assert status.finished is True
        assert status.status == "completed"
        assert len(status.results) == 1
        assert status.results[0].object_key == "papers/c.md"
        assert status.results[0].status == "succeeded"

        # 只有 c 被导入
        svc.import_paper.assert_called_once_with("papers/c.md")

    async def test_start_batch_import_single_failure_continues(self, mock_deps):
        """单个文件失败不中断整批，继续导入后续文件。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        mysql_import._batch_jobs.clear()
        minio_repo.list_md_files.return_value = [
            MinioFileItem(object_key="papers/a.md", size=1, last_modified=""),
            MinioFileItem(object_key="papers/b.md", size=1, last_modified=""),
        ]
        mysql_repo._execute.return_value = []  # 都未入库
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)
        svc.import_paper = AsyncMock(side_effect=[
            Exception("LLM 抽取失败"),
            PaperImportResponse(
                paper_id=gen_paper_id("papers/b.md"), title="", question_count=1,
            ),
        ])

        resp = await svc.start_batch_import()
        await mysql_import._batch_jobs[resp.job_id]["task"]

        status = svc.get_batch_status(resp.job_id)
        assert status.succeeded == 1
        assert status.failed == 1
        assert status.finished is True
        assert status.results[0].status == "failed"
        assert "LLM 抽取失败" in status.results[0].error
        assert status.results[1].status == "succeeded"
        assert svc.import_paper.call_count == 2

    async def test_get_batch_status_not_found(self, mock_deps):
        """轮询不存在的 job_id 抛 AppError(404)。"""
        minio_repo, mysql_repo, llm_svc, prompt_svc = mock_deps
        svc = MySqlImportService(minio_repo, mysql_repo, llm_svc, prompt_svc)

        with pytest.raises(AppError) as exc_info:
            svc.get_batch_status("nonexistent_job")
        assert exc_info.value.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_service/test_mysql_import.py -v`
Expected: 3 个新用例 FAIL，报 `AttributeError: 'MySqlImportService' object has no attribute 'start_batch_import'` 或 `ImportError`（`BatchImportResponse` 未定义）。

- [ ] **Step 3: 写最小实现**

**3a. `model/mysql_schemas.py`** 末尾追加：

```python
class BatchImportResponse(BaseModel):
    job_id: str
    total: int
    skipped: int
    status: str = "running"


class BatchFileResult(BaseModel):
    object_key: str
    paper_id: str
    status: str  # "succeeded" | "failed"
    error: str | None = None


class BatchImportStatusResponse(BaseModel):
    job_id: str
    status: str  # "running" | "completed"
    total: int
    succeeded: int
    failed: int
    skipped: int
    finished: bool
    results: list[BatchFileResult] = Field(default_factory=list)
```

**3b. `service/mysql_import.py`** 顶部 import 区：

- 第 3 行 `import csv` 上方插入两行：

```python
import asyncio
import uuid
```

- 在 `from model.mysql_schemas import (` 块内追加 `BatchImportResponse,`、`BatchFileResult,`、`BatchImportStatusResponse,`（按字母序插入）。
- 在 `from logs.logging import get_logger` 之前（或 `from libs.mysql import MySqlRepository` 附近）追加：

```python
from core.exceptions import AppError
```

- 在 `log = get_logger(__name__)` 之后、`@log_step` 之前追加模块级注册表：

```python
# 进程内批量导入 job 注册表（重启即失，一次性操作可重跑）
_batch_jobs: dict[str, dict] = {}
```

**3c.** 在 `MySqlImportService` 类末尾（`get_weak_kp_recommend` 方法之后）追加 3 个方法：

```python
    async def start_batch_import(self) -> BatchImportResponse:
        """一键批量增量导入：列出桶内全部 .md，跳过已入库，后台逐个 import_paper。"""
        md_files = await self._minio.list_md_files(prefix="", limit=100000)
        existing_rows = await self._mysql._execute("SELECT id FROM exam_papers")
        existing_ids = {row["id"] for row in existing_rows}

        to_import = [
            f.object_key for f in md_files
            if gen_paper_id(f.object_key) not in existing_ids
        ]
        skipped = len(md_files) - len(to_import)
        job_id = uuid.uuid4().hex

        _batch_jobs[job_id] = {
            "task": asyncio.create_task(self._run_batch(job_id, to_import)),
            "status": "running",
            "total": len(md_files),
            "succeeded": 0,
            "failed": 0,
            "skipped": skipped,
            "finished": False,
            "results": [],
        }
        log.info(
            "批量增量导入已启动: job_id=%s, total=%d, skipped=%d, to_import=%d",
            job_id, len(md_files), skipped, len(to_import),
        )
        return BatchImportResponse(
            job_id=job_id, total=len(md_files), skipped=skipped,
        )

    async def _run_batch(self, job_id: str, object_keys: list[str]) -> None:
        """后台顺序导入；单个文件失败记录后继续，不中断整批。"""
        job = _batch_jobs[job_id]
        for key in object_keys:
            try:
                result = await self.import_paper(key)
                job["succeeded"] += 1
                job["results"].append({
                    "object_key": key,
                    "paper_id": result.paper_id,
                    "status": "succeeded",
                    "error": None,
                })
            except Exception as exc:
                job["failed"] += 1
                job["results"].append({
                    "object_key": key,
                    "paper_id": gen_paper_id(key),
                    "status": "failed",
                    "error": str(exc),
                })
                log.warning("批量导入单文件失败: %s, err=%s", key, exc)
        job["status"] = "completed"
        job["finished"] = True
        log.info(
            "批量增量导入完成: job_id=%s, succeeded=%d, failed=%d",
            job_id, job["succeeded"], job["failed"],
        )

    def get_batch_status(self, job_id: str) -> BatchImportStatusResponse:
        """查询批量导入进度；job 不存在抛 AppError(404)。"""
        job = _batch_jobs.get(job_id)
        if job is None:
            raise AppError(
                f"批量导入任务不存在: {job_id}",
                status_code=404,
                detail={"job_id": job_id},
            )
        return BatchImportStatusResponse(
            job_id=job_id,
            status=job["status"],
            total=job["total"],
            succeeded=job["succeeded"],
            failed=job["failed"],
            skipped=job["skipped"],
            finished=job["finished"],
            results=[BatchFileResult(**r) for r in job["results"]],
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/test_service/test_mysql_import.py -v`
Expected: 全部 PASS（含既有用例 + 3 个新用例）。

- [ ] **Step 5: 提交**

```bash
git add model/mysql_schemas.py service/mysql_import.py tests/unit/test_service/test_mysql_import.py
git commit -m "feat(mysql): 批量增量导入服务 — 列桶+跳过已入库+后台顺序导入+状态轮询"
```

---

### Task 2: 批量导入 API 端点

**Files:**
- Modify: `service/api/endpoints/mysql_import.py`（import 区 + 两个路由）

**Interfaces:**
- Consumes:
  - `get_mysql_import_service`（`service/api/deps.py`，已存在）
  - `MySqlImportService.start_batch_import() -> BatchImportResponse`（Task 1）
  - `MySqlImportService.get_batch_status(job_id) -> BatchImportStatusResponse`（Task 1）
  - `BatchImportResponse` / `BatchImportStatusResponse`（Task 1）
- Produces:
  - `POST /api/v1/mysql/import/batch`
  - `GET /api/v1/mysql/import/batch/{job_id}`

- [ ] **Step 1: 改 import 区**

`service/api/endpoints/mysql_import.py` 的 `from model.mysql_schemas import (` 块内追加：

```python
    BatchImportResponse,
    BatchImportStatusResponse,
```

- [ ] **Step 2: 追加两个路由**

在文件末尾（`recommend_weak_kp` 之后）追加：

```python
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
```

- [ ] **Step 3: 校验路由能正常挂载（无单元测试，遵循既有约定）**

Run: `python -c "from main import app; print([r.path for r in app.routes if 'batch' in r.path])"`
Expected: 输出 `['/api/v1/mysql/import/batch', '/api/v1/mysql/import/batch/{job_id}']`，且无异常。

- [ ] **Step 4: 跑全量单元测试确认无回归**

Run: `pytest tests/unit -q`
Expected: 全部 PASS（batch 相关 3 个用例在 Task 1 已通过，此处确认端点改动未破坏其余用例）。

- [ ] **Step 5: 提交**

```bash
git add service/api/endpoints/mysql_import.py
git commit -m "feat(mysql): 批量增量导入 API 端点 POST/import/batch + GET/import/batch/{job_id}"
```

---

## Self-Review

**1. Spec coverage:**
- 增量判定（paper_id 已入库即跳过）→ Task 1 `start_batch_import` 的 `existing_ids` 过滤 + 测试 `test_start_batch_import_skips_existing`。✔
- 后台任务 + 状态轮询 → Task 1 `asyncio.create_task` + `get_batch_status` + 测试。✔
- 进程内 `dict` 存状态 → Task 1 `_batch_jobs`。✔
- 顺序执行 + 单文件失败不中断 → Task 1 `_run_batch` + 测试 `test_start_batch_import_single_failure_continues`。✔
- 目标桶 `llm-construct`（`settings.minio_bucket`）→ 复用 `list_md_files`，无桶参数。✔
- 答案内嵌、不配对 → 复用 `import_paper`，无新增配对逻辑。✔
- 两个端点 → Task 2。✔
- 轮询不存在 job → 404 → Task 1 `get_batch_status` + 测试 `test_get_batch_status_not_found`。✔

**2. Placeholder scan:** 无 TBD/TODO/「实现略」/「类似 Task N」。✔

**3. Type consistency:**
- `start_batch_import() -> BatchImportResponse` 在 Task 1 定义、Task 2 消费，签名一致。✔
- `get_batch_status(job_id) -> BatchImportStatusResponse` 同步方法，端点直接 `return svc.get_batch_status(job_id)`（不 await），一致。✔
- DTO 字段名 `job_id/total/skipped/succeeded/failed/finished/results` 在 DTO、服务、测试三处一致。✔
