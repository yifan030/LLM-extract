# FastAPI 分层重构设计

> 基于 `2026-08-01-exam-knowledge-point-linking-design.md` 的流水线设计，将纯 CLI 工具重构为分层良好的 FastAPI Web 应用。

## 1. 目录结构与分层

```
exam_extract/
├── app/
│   ├── __init__.py
│   ├── main.py                        # FastAPI 应用工厂 + lifespan
│   ├── cli.py                         # CLI 入口（复用 services 层）
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                    # FastAPI Depends 依赖注入
│   │   └── v1/
│   │       ├── __init__.py
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── extraction.py      # POST /extract
│   │           ├── papers.py          # 试卷、题目查询
│   │           ├── knowledge.py       # 知识点查询
│   │           └── minio.py           # MinIO 文件浏览 + webhook
│   │
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── models.py                  # 领域模型（原 exam_extract/models.py）
│   │   └── schemas.py                 # API 请求/响应 DTO
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── extraction.py              # 流水线编排
│   │   ├── llm.py                     # LLM 调用
│   │   ├── prompt.py                  # Prompt 构建
│   │   ├── matcher.py                 # 知识点匹配
│   │   ├── knowledge.py              # 知识点服务
│   │   └── minio.py                   # MinIO 服务
│   │
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── hugegraph.py               # HugeGraph REST
│   │   └── minio.py                   # MinIO SDK
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                  # pydantic-settings
│   │   ├── exceptions.py              # 全局异常定义
│   │   ├── logging.py                 # 日志配置
│   │   └── events.py                  # Redis Streams 消费者
│   │
│   └── utils/
│       ├── __init__.py
│       └── snowflake.py               # 雪花 ID
│
├── prompts/
│   └── exam_extract.md
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_services/
│   │   ├── test_repositories/
│   │   └── test_domain/
│   ├── integration/
│   │   ├── test_api/
│   │   └── test_pipeline.py
│   └── fixtures/
├── requirements.txt
└── README.md
```

### 依赖方向（硬规则）

```
api/ ────→ services/ ────→ repositories/ ────→ 外部系统
  │            │               │
  └────────────┴───────────────┴──→ domain/  (纯数据，零依赖)
  所有层 ─────────────────────────→ core/    (横切配置)
  所有层 ─────────────────────────→ utils/   (纯工具)
```

## 2. API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/minio/files?prefix=&limit=50` | MinIO `.md` 文件列表 |
| POST | `/api/v1/minio/webhook/minio` | MinIO bucket notification 回调 |
| GET | `/api/v1/papers` | 试卷列表（分页） |
| GET | `/api/v1/papers/{paper_id}` | 试卷详情 + 题目列表 |
| GET | `/api/v1/papers/{paper_id}/questions` | 该试卷所有题目 |
| GET | `/api/v1/questions/{question_id}` | 单题详情 + 关联知识点 |
| GET | `/api/v1/knowledge` | 知识点列表（按 level 筛选） |
| GET | `/api/v1/knowledge/{kp_id}` | 知识点详情 + 关联题目 |
| POST | `/api/v1/extract` | 手动触发抽取流水线 |
| GET | `/health` | 健康检查 |

### POST /extract 请求体

```json
{ "object_key": "exams/2024-xx.md" }
```

### POST /extract 响应体

```json
{
  "paper_id": "paper_xxx",
  "question_count": 20,
  "matched_kp": 76
}
```

## 3. 数据模型

### 领域模型（`domain/models.py`）

保持现有 Pydantic 模型不变，供内部流水线使用：

- `ExamPaper`, `QuestionType`, `Question`, `LlmExtractResult` — LLM 抽取结果
- `Vertex`, `Edge`, `UnmatchedItem`, `IntermediateJson` — 中间 JSON 和图结构
- `Metadata` — 元数据

### API Schemas（`domain/schemas.py`）

面向外部消费者的请求/响应 DTO，与领域模型独立：

- `ExtractRequest` — object_key
- `ExtractResult` — paper_id, question_count, matched_kp
- `MinioFileItem` — object_key, size, last_modified
- `PaperSummary`, `QuestionSummary` — 列表项
- `PaperDetail`, `QuestionDetail` — 详情
- `KnowledgePointItem`, `KnowledgePointDetail`
- `PaginatedResponse[T]` — 泛型分页

## 4. 依赖注入（`api/deps.py`）

每个 `get_*` 是同步工厂函数，通过 FastAPI `Depends()` 注入路由：

```text
get_settings         → Settings
get_redis            → Redis
get_minio_repo       → MinioRepository
get_hg_repo          → HugeGraphRepository
get_llm_service      → LlmService
get_prompt_service   → PromptService
get_matcher_service  → MatcherService
get_extraction_service → ExtractionService (组装所有子服务)
get_knowledge_service  → KnowledgeService
```

## 5. 异常处理

定义 `AppError` 基类（`core/exceptions.py`），子类化具体异常：

- `MinioObjectNotFound` (404)
- `LlmApiCallError` (502)
- `HugeGraphError` (502)
- `KnowledgePointNotFound` (404)
- `ExtractionValidationError` (422)

`main.py` 注册三个 handler：`AppError`（业务异常）→ `ValidationError`（Pydantic 校验）→ `Exception`（兜底 500）。

## 6. 配置（`core/config.py`）

通过 `pydantic-settings` 从 `.env` 文件和环境变量加载，分 6 组：

- **LLM** — api_key, base_url, model, temperature, max_tokens, timeout
- **HugeGraph** — host, port, user, passwd, graphspace, graph
- **MinIO** — endpoint, access_key, secret_key, bucket, secure
- **Redis** — redis_url
- **App** — debug

## 7. 事件驱动（`core/events.py`）

```
MinIO Bucket Notification (s3:ObjectCreated:Put)
  → POST /api/v1/minio/webhook/minio
  → 过滤 .md 文件
  → XADD extract:events {object_key}
  → Consumer Group (exam-extract) 消费
  → ExtractionService.run(object_key)
  → XACK
```

应用 startup 时 `asyncio.create_task(start_consumer(...))`，shutdown 时 cancel。

## 8. 异步策略

全链路 `async/await`：

- LLM 调用：`AsyncOpenAI`
- HugeGraph 请求：`httpx.AsyncClient`
- MinIO 操作：`minio-py` 的 async 方法
- Redis：`redis-py` 异步客户端
- FastAPI 端点：`async def`

## 9. CLI 保留

```python
# app/cli.py
# 入口：python -m exam_extract.cli --object-key exams/xx.md
# 直接调用 Service 层，不经过 HTTP
async def main():
    settings = Settings()
    # 手动组装依赖 → 调 ExtractionService.run(object_key)
```

## 10. 测试策略

- **单元测试**：每层独立，mock 下层依赖
  - `test_services/` — mock repositories
  - `test_repositories/` — mock httpx / minio sdk
  - `test_domain/` — Pydantic 模型校验
- **集成测试**：API 端点用 TestClient + mock 外部依赖
- **流水线测试**：全链路用真实 LLM + HugeGraph（标记 slow）
- **现有测试迁移**：`test_models.py` → `test_domain/`，`test_matcher/test_prompt/test_llm.py` → `test_services/`，`test_adapter.py` → `test_repositories/`，`test_integration.py` → `integration/`

## 11. 清理项

- 删除根目录 `graph_service.py`（割接项目代码，无关联）
- 删除根目录 `reference.md`（无关文件）
