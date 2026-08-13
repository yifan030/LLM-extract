# MySQL 批量增量导入 API 设计

> 状态：已确认 | 日期：2026-08-13

## 背景

现有 MySQL 独立导入通道（`MySqlImportService.import_paper`）只能**单篇**导入：

```
POST /api/v1/mysql/import/paper  { "object_key": "..." }
```

当 MinIO 的 `llm-construct` 桶里积累了大量 `.md` 试卷时，需要一篇一篇手动调用，效率低。本设计新增一个**一键批量增量导入**接口：一次列出桶内全部 `.md` 文件，把「尚未入库」的文件批量导入 MySQL，并对已入库的文件跳过。

## 核心决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 增量判定 | 按 `paper_id` 是否已存在于 `exam_papers` 表 | 实现最简单；`paper_id = MD5(object_key)`，已入库即跳过 |
| 执行模型 | 后台任务 + 状态轮询 | 逐篇跑 LLM 抽取，多文件耗时数分钟，同步请求会超时 |
| job 状态存储 | 进程内 `dict` | 一次性操作，重启丢失可重跑；与现有进程级单例风格一致 |
| 执行顺序 | 顺序（非并发） | LLM 抽取慢，顺序最稳、不冲击 LLM 限流 |
| 目标桶 | `settings.minio_bucket`（当前 `.env` = `llm-construct`） | 直接复用 `MinioRepository`，无新增桶参数 |
| 单文件失败 | 记录后继续 | 一个坏文件不应中断整批 |

### 已知限制（接受）

- **增量以 `paper_id`（文件路径的 MD5）为准，不以内容为准**：同一个 object key 下内容变化时，`paper_id` 不变，会被判为「已导入」而跳过，不会重新抽取。如需覆盖，后续可加 `force` 参数。
- 试卷写入「非事务」：`exam_papers` 与 `questions` 分多次 upsert，若中途崩溃可能留下「有试卷、缺部分题」的半成品。该半成品仍会被判为「已导入」跳过。当前接受，后续如需可引入导入状态标记列。

## API 设计

### `POST /api/v1/mysql/import/batch`

触发批量增量导入，立即返回 job_id 与摘要。

```json
// Request（无请求体）
{}

// Response 200
{
    "job_id": "a1b2c3d4e5f6",
    "total": 12,          // 桶内全部 .md 文件数
    "skipped": 9,         // 已入库、被跳过的文件数
    "status": "running"   // 固定 running
}
```

**流程**：

```
list_md_files(limit=大)                 # llm-construct 桶全部 .md
  → SELECT id FROM exam_papers         # 一次拿到已入库 paper_id 集合
  → 过滤掉 gen_paper_id(object_key) 已存在的文件
  → asyncio.create_task(顺序逐个 import_paper)   # 复用现有单篇导入
  → 返回 {job_id, total, skipped, status:"running"}
```

前置阶段（列 MinIO / 查 MySQL）失败 → 抛 `AppError`，不创建 job。

### `GET /api/v1/mysql/import/batch/{job_id}`

轮询进度。

```json
// Response 200
{
    "job_id": "a1b2c3d4e5f6",
    "status": "completed",     // running | completed
    "total": 12,
    "succeeded": 2,
    "failed": 1,
    "skipped": 9,
    "finished": true,
    "results": [
        {"object_key": "papers/a.md", "paper_id": "paper_xxx", "status": "succeeded", "error": null},
        {"object_key": "papers/b.md", "paper_id": "paper_yyy", "status": "failed", "error": "LLM 抽取超时"}
    ]
}
```

- `results` 仅包含**本次实际处理**（succeeded + failed）的文件，不含 skipped。
- 未找到 job → 抛 `AppError`（404）。

## 组件与数据流

### 1. DTO（`model/mysql_schemas.py`）

```python
class BatchImportResponse(BaseModel):
    job_id: str
    total: int
    skipped: int
    status: str = "running"

class BatchFileResult(BaseModel):
    object_key: str
    paper_id: str
    status: str          # "succeeded" | "failed"
    error: str | None = None

class BatchImportStatusResponse(BaseModel):
    job_id: str
    status: str          # "running" | "completed"
    total: int
    succeeded: int
    failed: int
    skipped: int
    finished: bool
    results: list[BatchFileResult] = Field(default_factory=list)
```

### 2. 服务层（`service/mysql_import.py`）

新增两个方法 + 模块级 job 注册表：

```python
# 模块级进程内 job 注册表
_batch_jobs: dict[str, dict] = {}

class MySqlImportService:
    def start_batch_import(self) -> BatchImportResponse:
        """列出 .md → 过滤已入库 → 起后台任务 → 返回 job_id。"""

    def get_batch_status(self, job_id: str) -> BatchImportStatusResponse:
        """返回进程内 job 状态，不存在抛 AppError。"""
```

- `start_batch_import` 是**同步**方法（`asyncio.create_task` 起后台协程），内部先做前置过滤（同步 await），再创建后台任务。
- 后台协程 `_run_batch(job_id, to_import)` 顺序 `await self.import_paper(key)`，每个包 `try/except` 更新注册表。
- job_id 用 `uuid.uuid4().hex`。

### 3. 端点（`service/api/endpoints/mysql_import.py`）

```python
@router.post("/import/batch", response_model=BatchImportResponse, tags=["mysql"])
async def import_batch(svc: MySqlImportService = Depends(get_mysql_import_service)):
    return svc.start_batch_import()

@router.get("/import/batch/{job_id}", response_model=BatchImportStatusResponse, tags=["mysql"])
async def import_batch_status(job_id: str, svc: MySqlImportService = Depends(get_mysql_import_service)):
    return svc.get_batch_status(job_id)
```

## 错误处理

| 场景 | 处理 |
|---|---|
| 前置阶段：MinIO 列不出 / MySQL 查不到 | 抛 `AppError`，不创建 job |
| 单个文件 import_paper 抛异常 | 记录 `failed` + `error`，继续下一个文件 |
| 后台任务整体被取消（进程关闭） | job 停留在 `running`，重启后重新触发即可 |
| 轮询不存在的 job_id | 抛 `AppError`（404） |

## 测试

单测（`tests/unit/test_service/test_mysql_import.py`，沿用现有 fixture）：

1. **跳过已入库**：mock `list_md_files` 返回 3 个文件、`exam_papers` 已有其中 2 个的 `paper_id`，断言 `to_import` 只含 1 个，`skipped=2`。
2. **单文件失败不中断**：mock `import_paper` 对第 1 个抛异常、第 2 个成功，断言 `failed=1`、`succeeded=1`、job `completed`。
3. **状态轮询**：`get_batch_status` 返回正确计数与 `finished` 标志。
4. **轮询不存在 job**：断言抛 `AppError`。

## 与现有系统的边界

```
现有（不动）：
  单篇 POST /import/paper        → LLM 抽取 → MySQL
  单篇 POST /import/answers      → 解析 → MySQL
  单篇 POST /import/answer-sheet → OCR → MySQL

新增（复用单篇导入）：
  POST /import/batch  → 列桶 + 过滤 + 后台顺序调 import_paper
  GET  /import/batch/{job_id} → 轮询进度

复用：
  - MinioRepository.list_md_files / get_object_text
  - MySqlImportService.import_paper（单篇导入逻辑）
  - libs/id_gen.gen_paper_id
```

## 后续扩展

- **`force` 全量重导参数**：绕过「已入库跳过」，用于内容变更后强制重抽。
- **`concurrency` 并发参数**：受控并发（如 semaphore=3）加速大批量导入。
- **job 状态持久化**：迁移到 Redis，支持多 worker 与重启恢复。
- **导入状态标记列**：区分「已导入」与「半成品」，解决非事务写入的遗留问题。
