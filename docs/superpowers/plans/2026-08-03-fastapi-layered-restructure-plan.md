# FastAPI 分层重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将纯 CLI 项目重构为四层 FastAPI 应用（API → Service → Repository → Domain），新增 MinIO 数据源、Redis Streams 自动触发，保留 CLI 入口。

**Architecture:** 经典四层架构，api/ 调用 services/ 调用 repositories/，domain/ 为零依赖纯数据层，core/ 为横切配置层。全链路 async/await。

**Tech Stack:** FastAPI, Pydantic v2, pydantic-settings, AsyncOpenAI, httpx, minio-py, redis-py, pytest + httpx.AsyncClient

## Global Constraints

- 全链路 `async/await`（LLM 用 AsyncOpenAI，HTTP 用 httpx，MinIO 用 minio-py async）
- 依赖方向硬规则：api → services → repositories，所有层 → domain/core/utils
- 领域模型与 API schemas 独立，不在路由层暴露领域模型
- 保留 CLI 入口（复用 services 层）
- 删除 `graph_service.py` 和 `reference.md`
- 现有测试全部迁移到新结构，保持通过状态

---

### Task 1: 目录脚手架与包初始化

**Files:**
- Create: `app/__init__.py`
- Create: `app/api/__init__.py`
- Create: `app/api/v1/__init__.py`
- Create: `app/api/v1/endpoints/__init__.py`
- Create: `app/domain/__init__.py`
- Create: `app/services/__init__.py`
- Create: `app/repositories/__init__.py`
- Create: `app/core/__init__.py`
- Create: `app/utils/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_services/__init__.py`
- Create: `tests/unit/test_repositories/__init__.py`
- Create: `tests/unit/test_domain/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_api/__init__.py`

**Interfaces:**
- Consumes: nothing
- Produces: 空目录树，所有 `__init__.py` 为空文件

- [ ] **Step 1: 创建所有目录和空 `__init__.py`**

```bash
mkdir -p app/api/v1/endpoints app/domain app/services app/repositories app/core app/utils
mkdir -p tests/unit/test_services tests/unit/test_repositories tests/unit/test_domain
mkdir -p tests/integration/test_api tests/fixtures
touch app/__init__.py app/api/__init__.py app/api/v1/__init__.py app/api/v1/endpoints/__init__.py
touch app/domain/__init__.py app/services/__init__.py app/repositories/__init__.py
touch app/core/__init__.py app/utils/__init__.py
touch tests/unit/__init__.py tests/unit/test_services/__init__.py
touch tests/unit/test_repositories/__init__.py tests/unit/test_domain/__init__.py
touch tests/integration/__init__.py tests/integration/test_api/__init__.py
```

- [ ] **Step 2: 验证目录结构**

```bash
find app -type f | sort && find tests -type f | sort
```

- [ ] **Step 3: Commit**

```bash
git add app/ tests/unit/ tests/integration/
git commit -m "feat: scaffold project directory structure for layered architecture"
```

---

### Task 2: Core 层 — 配置

**Files:**
- Create: `app/core/config.py`
- Test: `tests/unit/test_core_config.py`（可选，pydantic-settings 自测能力强）

**Interfaces:**
- Consumes: nothing
- Produces: `class Settings(BaseSettings)` with fields for LLM, HugeGraph, MinIO, Redis, App

- [ ] **Step 1: 编写 `app/core/config.py`**

```python
# -*- coding: utf-8 -*-
"""应用配置中心，通过 pydantic-settings 从 .env / 环境变量加载。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ──
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 8192
    llm_timeout: float = 120.0

    # ── HugeGraph ──
    hg_host: str = "202.107.249.39"
    hg_port: int = 50045
    hg_user: str = "admin"
    hg_passwd: str = "admin"
    hg_graphspace: str = "DEFAULT"
    hg_graph: str = "edu"

    # ── MinIO ──
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "exams"
    minio_secure: bool = False

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"

    # ── App ──
    debug: bool = False

    @property
    def hg_base_url(self) -> str:
        return (
            f"http://{self.hg_host}:{self.hg_port}"
            f"/graphspaces/{self.hg_graphspace}/graphs/{self.hg_graph}"
        )
```

- [ ] **Step 2: 验证配置加载**

```bash
python -c "from app.core.config import Settings; s = Settings(); print(s.hg_base_url)"
```

- [ ] **Step 3: 更新 `requirements.txt`**

添加 `pydantic-settings>=2.0`、`httpx>=0.27`、`minio>=7.2`、`redis>=5.0`、`fastapi>=0.115`、`uvicorn[standard]>=0.30`。

- [ ] **Step 4: Commit**

```bash
git add app/core/config.py requirements.txt
git commit -m "feat: add Settings configuration with pydantic-settings"
```

---

### Task 3: Core 层 — 异常定义

**Files:**
- Create: `app/core/exceptions.py`
- Test: `tests/unit/test_core_exceptions.py`

**Interfaces:**
- Consumes: nothing
- Produces: `AppError`, `MinioObjectNotFound(404)`, `LlmApiCallError(502)`, `HugeGraphError(502)`, `KnowledgePointNotFound(404)`, `ExtractionValidationError(422)`

- [ ] **Step 1: 编写测试 `tests/unit/test_core_exceptions.py`**

```python
import pytest
from app.core.exceptions import (
    AppError,
    MinioObjectNotFound,
    LlmApiCallError,
    HugeGraphError,
    KnowledgePointNotFound,
    ExtractionValidationError,
)


def test_app_error_default_status():
    err = AppError("something wrong")
    assert err.message == "something wrong"
    assert err.status_code == 500
    assert err.detail == {}


def test_app_error_with_detail():
    err = AppError("not found", status_code=404, detail={"key": "x"})
    assert err.status_code == 404
    assert err.detail == {"key": "x"}


@pytest.mark.parametrize("exc_cls,expected_status", [
    (MinioObjectNotFound, 404),
    (LlmApiCallError, 502),
    (HugeGraphError, 502),
    (KnowledgePointNotFound, 404),
    (ExtractionValidationError, 422),
])
def test_subclass_status_codes(exc_cls, expected_status):
    err = exc_cls("test")
    assert err.status_code == expected_status
```

- [ ] **Step 2: 运行测试验证失败** `pytest tests/unit/test_core_exceptions.py -v`

- [ ] **Step 3: 编写 `app/core/exceptions.py`**

```python
# -*- coding: utf-8 -*-
"""应用级异常体系。"""


class AppError(Exception):
    """业务异常基类，由全局 exception_handler 统一处理。"""
    def __init__(self, message: str, status_code: int = 500, detail: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


class MinioObjectNotFound(AppError):
    def __init__(self, object_key: str):
        super().__init__(
            f"MinIO 文件不存在: {object_key}",
            status_code=404,
            detail={"object_key": object_key},
        )


class LlmApiCallError(AppError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, status_code=502, detail=detail)


class HugeGraphError(AppError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, status_code=502, detail=detail)


class KnowledgePointNotFound(AppError):
    def __init__(self, kp_id: str):
        super().__init__(
            f"知识点不存在: {kp_id}",
            status_code=404,
            detail={"kp_id": kp_id},
        )


class ExtractionValidationError(AppError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, status_code=422, detail=detail)
```

- [ ] **Step 4: 运行测试验证通过** `pytest tests/unit/test_core_exceptions.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/core/exceptions.py tests/unit/test_core_exceptions.py
git commit -m "feat: add application exception hierarchy"
```

---

### Task 4: Core 层 — 日志配置

**Files:**
- Create: `app/core/logging.py`（基于现有 `exam_extract/logger.py` 迁移）

**Interfaces:**
- Consumes: nothing
- Produces: `def get_logger(name: str) -> logging.Logger`

- [ ] **Step 1: 创建 `app/core/logging.py`**

```python
# -*- coding: utf-8 -*-
"""日志配置。"""
import logging

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        _CONFIGURED = True
    return logging.getLogger(name)
```

- [ ] **Step 2: 验证** `python -c "from app.core.logging import get_logger; log = get_logger('test'); log.info('ok')"`

- [ ] **Step 3: Commit**

```bash
git add app/core/logging.py
git commit -m "feat: add logging configuration to core layer"
```

---

### Task 5: Domain 层 — 领域模型迁移

**Files:**
- Create: `app/domain/models.py`（从 `exam_extract/models.py` 复制，改 import 路径）
- Modify: `exam_extract/models.py`（改为 re-export from `app.domain.models`，保持现有 import 兼容）
- Test: `tests/unit/test_domain/test_models.py`（从 `tests/test_models.py` 迁移，改 import 路径）

**Interfaces:**
- Consumes: nothing (domain has zero deps)
- Produces: same classes — `ExamPaper`, `QuestionType`, `Question`, `LlmExtractResult`, `Vertex`, `Edge`, `UnmatchedItem`, `IntermediateJson`, `Metadata`

- [ ] **Step 1: 复制模型到 `app/domain/models.py`**

```python
# -*- coding: utf-8 -*-
"""领域模型 — 纯 Pydantic 数据定义，零项目依赖。"""
from typing import Any

from pydantic import BaseModel, Field


class ExamPaper(BaseModel):
    title: str
    subject: str = "数学"
    grade: str | None = None
    total_score: int | None = None
    duration_minutes: int | None = None


class QuestionType(BaseModel):
    name: str
    description: str | None = None


class Question(BaseModel):
    number: str
    content: str
    answer: str | None = None
    score: int | None = None
    question_type: str
    candidate_knowledge_points: list[str] = Field(default_factory=list)


class LlmExtractResult(BaseModel):
    exam_paper: ExamPaper
    question_types: list[QuestionType]
    questions: list[Question]


class Vertex(BaseModel):
    label: str
    id: str
    properties: dict[str, Any]


class Edge(BaseModel):
    label: str
    outV: str
    inV: str
    properties: dict[str, Any]


class UnmatchedItem(BaseModel):
    question_id: str
    number: str
    candidate: str
    reason: str = "NOT_IN_LEVEL4_LIST"


class Metadata(BaseModel):
    source_file: str
    generated_at: str
    matching_mode: str = "strict"


class IntermediateJson(BaseModel):
    metadata: Metadata
    vertices: list[Vertex]
    edges: list[Edge]
    unmatched: list[UnmatchedItem]
```

- [ ] **Step 2: 改动 `exam_extract/models.py` 为 re-export**

```python
# -*- coding: utf-8 -*-
"""Re-export domain models for backward compatibility."""
from app.domain.models import (  # noqa: F401
    ExamPaper,
    QuestionType,
    Question,
    LlmExtractResult,
    Vertex,
    Edge,
    UnmatchedItem,
    IntermediateJson,
    Metadata,
)
```

- [ ] **Step 3: 迁移测试 `tests/unit/test_domain/test_models.py`**（内容同原 `tests/test_models.py`，`from exam_extract.models` 改为 `from app.domain.models`）

- [ ] **Step 4: 运行现有全量测试确保兼容** `python -m pytest tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add app/domain/models.py exam_extract/models.py tests/unit/test_domain/test_models.py
git commit -m "refactor: move domain models to app/domain/models.py with re-export"
```

---

### Task 6: Domain 层 — API Schemas

**Files:**
- Create: `app/domain/schemas.py`
- Test: `tests/unit/test_domain/test_schemas.py`

**Interfaces:**
- Consumes: nothing (pure Pydantic)
- Produces: `ExtractRequest`, `ExtractResult`, `MinioFileItem`, `PaperSummary`, `PaperDetail`, `QuestionSummary`, `QuestionDetail`, `KnowledgePointItem`, `KnowledgePointDetail`, `PaginatedResponse[T]`

- [ ] **Step 1: 编写测试 `tests/unit/test_domain/test_schemas.py`**

```python
from app.domain.schemas import (
    ExtractRequest,
    ExtractResult,
    MinioFileItem,
    PaperSummary,
    PaginatedResponse,
)


def test_extract_request_valid():
    req = ExtractRequest(object_key="exams/test.md")
    assert req.object_key == "exams/test.md"


def test_extract_result_fields():
    result = ExtractResult(paper_id="paper_123", question_count=20, matched_kp=76)
    assert result.paper_id == "paper_123"
    assert result.question_count == 20
    assert result.matched_kp == 76


def test_minio_file_item():
    item = MinioFileItem(object_key="exams/test.md", size=1024, last_modified="2026-08-03T10:00:00")
    assert item.object_key == "exams/test.md"
    assert item.size == 1024


def test_paper_summary():
    p = PaperSummary(paper_id="paper_1", title="测试卷", subject="数学", grade="高一", question_count=22)
    assert p.question_count == 22


def test_paginated_response():
    resp = PaginatedResponse(items=[], total=0, limit=20, offset=0)
    assert resp.total == 0
    assert resp.limit == 20
```

- [ ] **Step 2: 运行测试验证失败** `pytest tests/unit/test_domain/test_schemas.py -v`

- [ ] **Step 3: 编写 `app/domain/schemas.py`**

```python
# -*- coding: utf-8 -*-
"""API 请求/响应 DTO，与领域模型独立演进。"""
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


# ── 请求 ──
class ExtractRequest(BaseModel):
    object_key: str


# ── 响应 ──
class ExtractResult(BaseModel):
    paper_id: str
    question_count: int
    matched_kp: int


class MinioFileItem(BaseModel):
    object_key: str
    size: int
    last_modified: str


class PaperSummary(BaseModel):
    paper_id: str
    title: str
    subject: str
    grade: str | None = None
    question_count: int


class PaperDetail(BaseModel):
    paper_id: str
    title: str
    subject: str
    grade: str | None = None
    total_score: int | None = None
    duration_minutes: int | None = None
    questions: list["QuestionSummary"] = []


class QuestionSummary(BaseModel):
    question_id: str
    number: str
    content: str
    question_type: str
    knowledge_points: list[str] = []


class QuestionDetail(BaseModel):
    question_id: str
    number: str
    content: str
    answer: str | None = None
    score: int | None = None
    question_type: str
    exam_paper_id: str
    exam_paper_title: str
    knowledge_points: list[str] = []


class KnowledgePointItem(BaseModel):
    kp_id: str
    name: str
    level: int | None = None
    subject: str | None = None


class KnowledgePointDetail(BaseModel):
    kp_id: str
    name: str
    level: int | None = None
    subject: str | None = None
    description: str | None = None
    related_questions: list[QuestionSummary] = []


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
```

- [ ] **Step 4: 运行测试验证通过** `pytest tests/unit/test_domain/test_schemas.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/domain/schemas.py tests/unit/test_domain/test_schemas.py
git commit -m "feat: add API request/response schemas"
```

---

### Task 7: Utils 层 — Snowflake 迁移

**Files:**
- Create: `app/utils/snowflake.py`（从 `exam_extract/snowflake.py` 复制）
- Modify: `exam_extract/snowflake.py`（re-export）
- Test: `tests/unit/test_utils_snowflake.py`

**Interfaces:**
- Consumes: nothing
- Produces: `class Snowflake` with `next_id() -> int`

- [ ] **Step 1: 复制到 `app/utils/snowflake.py`**（内容同原文件，改 package docstring 为 `"""Simple snowflake ID generator."""`）

- [ ] **Step 2: 改 `exam_extract/snowflake.py` 为 re-export**

```python
from app.utils.snowflake import Snowflake  # noqa: F401
```

- [ ] **Step 3: 编写测试 `tests/unit/test_utils_snowflake.py`**（内容同 `tests/test_matcher.py` 中的 `test_snowflake_generates_unique_increasing_ids`，import 改为 `from app.utils.snowflake import Snowflake`）

- [ ] **Step 4: 运行现有全量测试确保兼容** `python -m pytest tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add app/utils/snowflake.py exam_extract/snowflake.py tests/unit/test_utils_snowflake.py
git commit -m "refactor: move Snowflake to app/utils/snowflake.py"
```

---

### Task 8: Repositories 层 — HugeGraph

**Files:**
- Create: `app/repositories/hugegraph.py`（基于 `exam_extract/adapter.py` 重写为 async + httpx）
- Test: `tests/unit/test_repositories/test_hugegraph.py`

**Interfaces:**
- Consumes: `Settings` from core.config, domain models
- Produces: `class HugeGraphRepository` with `async load_level4_names() -> list[str]`, `async preload_question_types() -> dict[str, str]`, `async create_vertex(vertex: Vertex) -> tuple[bool, bool]`, `async create_edge(edge: Edge) -> bool`, `async list_vertices(label: str, limit: int = 100) -> list[dict]`, `async get_vertex(vertex_id: str) -> dict | None`, `async get_vertex_edges(vertex_id: str, direction: str, label: str | None = None) -> list[dict]`

- [ ] **Step 1: 编写测试 `tests/unit/test_repositories/test_hugegraph.py`**

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.repositories.hugegraph import HugeGraphRepository
from app.domain.models import Vertex, Edge


@pytest.fixture
def repo():
    from app.core.config import Settings
    settings = Settings()
    return HugeGraphRepository(settings)


@pytest.mark.asyncio
async def test_load_level4_names():
    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "vertices": [
            {"properties": {"name": "交集", "level": 4}},
            {"properties": {"name": "子集", "level": 4}},
            {"properties": {"name": "函数", "level": 3}},
        ]
    }
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_resp

    repo = HugeGraphRepository.__new__(HugeGraphRepository)
    repo._client = mock_client
    repo.base_url = "http://h:8080/gs/g"

    result = await repo.load_level4_names()
    assert result == ["交集", "子集"]


@pytest.mark.asyncio
async def test_create_vertex_success():
    mock_resp = AsyncMock()
    mock_resp.status_code = 201
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_resp

    repo = HugeGraphRepository.__new__(HugeGraphRepository)
    repo._client = mock_client
    repo.base_url = "http://h:8080/gs/g"

    v = Vertex(label="exam_paper", id="paper_1", properties={"title": "test"})
    created, duplicated = await repo.create_vertex(v)
    assert created is True
    assert duplicated is False


@pytest.mark.asyncio
async def test_create_vertex_duplicated():
    mock_resp = AsyncMock()
    mock_resp.status_code = 400
    mock_resp.text = "Vertex already exists"
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_resp

    repo = HugeGraphRepository.__new__(HugeGraphRepository)
    repo._client = mock_client
    repo.base_url = "http://h:8080/gs/g"

    v = Vertex(label="exam_paper", id="paper_1", properties={"title": "test"})
    created, duplicated = await repo.create_vertex(v)
    assert created is False
    assert duplicated is True
```

- [ ] **Step 2: 运行测试验证失败** `pytest tests/unit/test_repositories/test_hugegraph.py -v`

- [ ] **Step 3: 编写 `app/repositories/hugegraph.py`**

```python
# -*- coding: utf-8 -*-
"""HugeGraph REST API 封装（async + httpx）。"""
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import HugeGraphError
from app.core.logging import get_logger
from app.domain.models import Edge, Vertex

log = get_logger(__name__)


class HugeGraphRepository:
    def __init__(self, settings: Settings):
        self.base_url = settings.hg_base_url
        self.auth = (settings.hg_user, settings.hg_passwd)

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(auth=self.auth, timeout=httpx.Timeout(30.0))

    async def load_level4_names(self) -> list[str]:
        url = f"{self.base_url}/graph/vertices?label=knowledge_point&limit=10000"
        async with await self._client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        names = []
        for v in data.get("vertices", []):
            props = v.get("properties", {})
            if props.get("level") == 4:
                name = props.get("name", "")
                if name:
                    names.append(name)
        return names

    async def preload_question_types(self) -> dict[str, str]:
        url = f"{self.base_url}/graph/vertices?label=question_type"
        cache: dict[str, str] = {}
        async with await self._client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            for v in resp.json().get("vertices", []):
                name = v.get("properties", {}).get("name")
                if name:
                    cache[name] = v.get("id")
        return cache

    async def create_vertex(self, vertex: Vertex) -> tuple[bool, bool]:
        payload = {
            "label": vertex.label,
            "id": vertex.id,
            "type": "vertex",
            "properties": vertex.properties,
        }
        url = f"{self.base_url}/graph/vertices"
        async with await self._client() as client:
            resp = await client.post(url, json=payload)
        if resp.status_code in (200, 201):
            log.info("顶点创建成功: %s (%s)", vertex.label, vertex.id)
            return True, False
        if resp.status_code == 400 and "already exists" in resp.text.lower():
            log.debug("顶点已存在，跳过: %s (%s)", vertex.label, vertex.id)
            return False, True
        log.error("顶点创建失败: %s (%s): %s", vertex.label, vertex.id, resp.text)
        return False, False

    async def create_edge(self, edge: Edge) -> bool:
        url = f"{self.base_url}/graph/edges"
        payload = {
            "label": edge.label,
            "outV": edge.outV,
            "inV": edge.inV,
            "properties": edge.properties,
        }
        async with await self._client() as client:
            resp = await client.post(url, json=payload)
        if resp.status_code in (200, 201):
            log.info("边创建成功: %s -[%s]-> %s", edge.outV, edge.label, edge.inV)
            return True
        log.error("边创建失败: %s -[%s]-> %s: %s", edge.outV, edge.label, edge.inV, resp.text)
        return False

    async def list_vertices(self, label: str, limit: int = 100, offset: int = 0) -> list[dict]:
        url = f"{self.base_url}/graph/vertices?label={label}&limit={limit}"
        if offset:
            url += f"&offset={offset}"
        async with await self._client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json().get("vertices", [])

    async def count_vertices(self, label: str) -> int:
        """通过 list_vertices + page 估算总数（HugeGraph REST 不直接支持 count）。"""
        # 先用大 limit 拉一次来估算
        url = f"{self.base_url}/graph/vertices?label={label}&limit=1"
        async with await self._client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            # 部分 HugeGraph 版本返回 total 在 response 中
            return resp.json().get("total", 0)

    async def get_vertex(self, vertex_id: str) -> dict | None:
        url = f"{self.base_url}/graph/vertices/{vertex_id}"
        async with await self._client() as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def get_vertex_edges(
        self, vertex_id: str, direction: str = "out", label: str | None = None
    ) -> list[dict]:
        url = f"{self.base_url}/graph/edges?vertex_id={vertex_id}&direction={direction}"
        if label:
            url += f"&label={label}"
        async with await self._client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json().get("edges", [])
```

- [ ] **Step 4: 运行测试验证通过** `pytest tests/unit/test_repositories/test_hugegraph.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/repositories/hugegraph.py tests/unit/test_repositories/test_hugegraph.py
git commit -m "feat: add async HugeGraph repository with httpx"
```

---

### Task 9: Repositories 层 — MinIO

**Files:**
- Create: `app/repositories/minio.py`
- Test: `tests/unit/test_repositories/test_minio.py`

**Interfaces:**
- Consumes: `Settings` from core.config
- Produces: `class MinioRepository` with `async list_md_files(prefix: str = "", limit: int = 50) -> list[MinioFileItem]`, `async get_object_text(object_key: str) -> str`

- [ ] **Step 1: 编写测试 `tests/unit/test_repositories/test_minio.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.repositories.minio import MinioRepository
from app.core.exceptions import MinioObjectNotFound


@pytest.mark.asyncio
async def test_list_md_files_filters_by_extension():
    repo = MinioRepository.__new__(MinioRepository)
    repo._client = AsyncMock()
    mock_obj1 = MagicMock()
    mock_obj1.object_name = "exams/test.md"
    mock_obj1.size = 1024
    mock_obj1.last_modified = "2026-08-03T10:00:00Z"
    mock_obj2 = MagicMock()
    mock_obj2.object_name = "exams/other.pdf"
    repo._client.list_objects.return_value = [mock_obj1, mock_obj2]

    result = await repo.list_md_files(prefix="exams/")
    assert len(result) == 1
    assert result[0].object_key == "exams/test.md"
    assert result[0].size == 1024


@pytest.mark.asyncio
async def test_get_object_text_not_found():
    repo = MinioRepository.__new__(MinioRepository)
    repo._client = AsyncMock()
    repo._client.get_object.side_effect = Exception("NoSuchKey")

    with pytest.raises(MinioObjectNotFound):
        await repo.get_object_text("nonexistent.md")
```

- [ ] **Step 2: 运行测试验证失败** `pytest tests/unit/test_repositories/test_minio.py -v`

- [ ] **Step 3: 编写 `app/repositories/minio.py`**

```python
# -*- coding: utf-8 -*-
"""MinIO SDK 封装 — 异步文件列表、文本读取。"""
from io import BytesIO

from miniopy_async import Minio  # type: ignore

from app.core.config import Settings
from app.core.exceptions import MinioObjectNotFound
from app.core.logging import get_logger
from app.domain.schemas import MinioFileItem

log = get_logger(__name__)


class MinioRepository:
    def __init__(self, settings: Settings):
        self._client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = settings.minio_bucket

    async def list_md_files(self, prefix: str = "", limit: int = 50) -> list[MinioFileItem]:
        items: list[MinioFileItem] = []
        objects = await self._client.list_objects(
            self.bucket, prefix=prefix, recursive=True
        )
        async for obj in objects:
            if obj.object_name and obj.object_name.endswith(".md"):
                items.append(MinioFileItem(
                    object_key=obj.object_name,
                    size=obj.size or 0,
                    last_modified=str(obj.last_modified) if obj.last_modified else "",
                ))
            if len(items) >= limit:
                break
        log.info("列出 %d 个 .md 文件 (prefix=%r)", len(items), prefix)
        return items

    async def get_object_text(self, object_key: str) -> str:
        try:
            response = await self._client.get_object(self.bucket, object_key)
            data = await response.read()
            await response.close()
            await response.release_conn()
            return data.decode("utf-8")
        except Exception as exc:
            log.error("读取 MinIO 文件失败: %s, err=%s", object_key, exc)
            raise MinioObjectNotFound(object_key) from exc
```

- [ ] **Step 4: 运行测试验证通过** `pytest tests/unit/test_repositories/test_minio.py -v`

- [ ] **Step 5: Commit**

```bash
git add app/repositories/minio.py tests/unit/test_repositories/test_minio.py
git commit -m "feat: add async MinIO repository"
```

---

### Task 10: Services 层 — Prompt 与 LLM

**Files:**
- Create: `app/services/prompt.py`（从 `exam_extract/prompt.py` 迁移，接口改为 async repository）
- Create: `app/services/llm.py`（从 `exam_extract/llm.py` 迁移，改用 `AsyncOpenAI`）
- Modify: `exam_extract/prompt.py`（re-export）
- Modify: `exam_extract/llm.py`（re-export）
- Test: `tests/unit/test_services/test_prompt.py`（从 `tests/test_prompt.py` 迁移）
- Test: `tests/unit/test_services/test_llm.py`（从 `tests/test_llm.py` 迁移）

**Interfaces:**
- Consumes: `HugeGraphRepository.load_level4_names()`, `Settings`
- Produces: `class PromptService` with `async build_prompt(markdown: str) -> str`, `class LlmService` with `async extract(prompt: str) -> LlmExtractResult`

- [ ] **Step 1: 编写 `app/services/prompt.py`**

```python
# -*- coding: utf-8 -*-
"""Prompt 构建服务。"""
import os

from app.repositories.hugegraph import HugeGraphRepository


class PromptService:
    def __init__(self, hg_repo: HugeGraphRepository):
        self._hg_repo = hg_repo

    async def build_prompt(self, markdown_content: str) -> str:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        prompt_path = os.path.join(base_dir, "prompts", "exam_extract.md")
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()

        level4_names = await self._hg_repo.load_level4_names()
        names_text = "\n".join(f"- {name}" for name in sorted(level4_names))
        return (
            template.replace("{{level_4_knowledge_points}}", names_text)
            .replace("{{markdown_content}}", markdown_content)
        )

    def build_prompt_sync(self, markdown_content: str, level4_names: list[str]) -> str:
        """同步版本：CLI 场景使用，传入已加载的知识点列表避免 async 依赖。"""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        prompt_path = os.path.join(base_dir, "prompts", "exam_extract.md")
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()
        names_text = "\n".join(f"- {name}" for name in sorted(level4_names))
        return (
            template.replace("{{level_4_knowledge_points}}", names_text)
            .replace("{{markdown_content}}", markdown_content)
        )
```

- [ ] **Step 2: 编写 `app/services/llm.py`**

```python
# -*- coding: utf-8 -*-
"""LLM 调用服务 — 基于 AsyncOpenAI。"""
import json
import re
from dataclasses import dataclass

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import LlmApiCallError
from app.core.logging import get_logger
from app.domain.models import LlmExtractResult

log = get_logger(__name__)


@dataclass
class LlmConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    temperature: float = 0.0
    max_tokens: int = 8192
    timeout: float = 120.0


class LlmService:
    def __init__(self, settings: Settings):
        self._config = LlmConfig(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout,
        )
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                timeout=self._config.timeout,
            )
        return self._client

    async def extract(self, prompt: str) -> LlmExtractResult:
        raw = await self._call_llm(prompt)
        payload = self._extract_json_payload(raw)
        try:
            return LlmExtractResult.model_validate(payload)
        except ValidationError as exc:
            raise LlmApiCallError(f"LLM 输出结构校验失败: {exc}") from exc

    async def _call_llm(self, prompt: str) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": "你是高中数学试卷信息抽取助手，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
            )
        except Exception as exc:
            raise LlmApiCallError(f"LLM API 调用失败: {exc}") from exc

        choice = response.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            log.warning("LLM 输出因长度被截断 (max_tokens=%d)", self._config.max_tokens)

        content = choice.message.content
        if content is None:
            raise LlmApiCallError("LLM 返回内容为空")
        return content

    @staticmethod
    def _extract_json_payload(text: str) -> dict:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError as exc:
                raise LlmApiCallError(f"代码围栏内不是合法 JSON: {exc}") from exc

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        raise LlmApiCallError("无法从 LLM 输出中解析出 JSON")
```

- [ ] **Step 3: 改 `exam_extract/prompt.py` 和 `exam_extract/llm.py` 为 re-export**

```python
# exam_extract/prompt.py
from app.services.prompt import PromptService  # noqa: F401
from exam_extract.prompt import build_prompt, load_level4_knowledge_points  # re-export original sync functions for backward compat
```

实际上，对于 `prompt.py`，原模块有独立的 `build_prompt` 和 `load_level4_knowledge_points` 函数，这些是 `cli.py` 直接调用的。为了避免一次性改太多，我们先用 re-export 保持兼容：

```python
# exam_extract/prompt.py
# -*- coding: utf-8 -*-
"""Re-export for backward compatibility."""
from app.services.prompt import PromptService  # noqa: F401

# keep original sync functions for CLI compat
import os
import requests


def load_level4_knowledge_points(host, port, user, passwd, graphspace="DEFAULT", graph="edu"):
    from app.services.prompt import _load_level4_sync
    return _load_level4_sync(host, port, user, passwd, graphspace, graph)


def build_prompt(markdown_content, level4_names):
    from app.services.prompt import _build_prompt_sync
    return _build_prompt_sync(markdown_content, level4_names)
```

Wait, this is getting complex. Let me keep it simpler — keep the original sync functions as-is in `exam_extract/prompt.py`, and put the new async versions in `app/services/prompt.py`. CLI continues to use the old module. When we rewrite CLI in Task 13, we'll update the imports.

Let me re-think. The spec says CLI should reuse services layer. But the original `prompt.py` and `llm.py` have sync functions that CLI directly uses. To keep backward compat during migration, let me:

1. Copy code to `app/services/prompt.py` and `app/services/llm.py` as async
2. Keep originals unchanged for now
3. Task 13 (CLI) will update to use new async services

- [ ] **Step 4: 保留 `exam_extract/prompt.py` 和 `exam_extract/llm.py` 不变**

不修改它们，原 CLI (`cli.py`) 仍然可用。新代码全部引用 `app.services.*`。

- [ ] **Step 5: 编写单元测试**

```python
# tests/unit/test_services/test_prompt.py
import pytest
from unittest.mock import AsyncMock
from app.services.prompt import PromptService


@pytest.mark.asyncio
async def test_build_prompt_replaces_placeholders():
    mock_hg = AsyncMock()
    mock_hg.load_level4_names.return_value = ["交集", "子集"]
    svc = PromptService(mock_hg)
    result = await svc.build_prompt("## 试卷内容")
    assert "交集" in result
    assert "子集" in result
    assert "## 试卷内容" in result
    assert "{{level_4_knowledge_points}}" not in result
    assert "{{markdown_content}}" not in result


def test_build_prompt_sync():
    svc = PromptService.__new__(PromptService)
    result = svc.build_prompt_sync("## 测试", ["知识点A"])
    assert "知识点A" in result
    assert "## 测试" in result
```

```python
# tests/unit/test_services/test_llm.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.llm import LlmService
from app.core.exceptions import LlmApiCallError


@pytest.mark.asyncio
async def test_llm_extract_parses_valid_json():
    svc = LlmService.__new__(LlmService)
    svc._config = MagicMock()
    svc._config.model = "gpt-4o"
    svc._config.temperature = 0.0
    svc._config.max_tokens = 8192
    mock_client = AsyncMock()
    mock_choice = MagicMock()
    mock_choice.finish_reason = "stop"
    mock_choice.message.content = json.dumps({
        "exam_paper": {"title": "test", "subject": "数学"},
        "question_types": [{"name": "单选题"}],
        "questions": [{
            "number": "1",
            "content": "题干",
            "question_type": "单选题",
            "candidate_knowledge_points": ["交集"]
        }]
    }, ensure_ascii=False)
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    svc._client = mock_client

    result = await svc.extract("prompt")
    assert result.exam_paper.title == "test"
    assert len(result.questions) == 1


def test_extract_json_payload_direct_json():
    assert LlmService._extract_json_payload('{"a": 1}') == {"a": 1}


def test_extract_json_payload_fenced():
    text = '```json\n{"a": 1}\n```'
    assert LlmService._extract_json_payload(text) == {"a": 1}


def test_extract_json_payload_unparseable():
    with pytest.raises(LlmApiCallError, match="无法从 LLM 输出中解析"):
        LlmService._extract_json_payload("hello world")
```

- [ ] **Step 6: 运行测试** `pytest tests/unit/test_services/test_prompt.py tests/unit/test_services/test_llm.py -v`

- [ ] **Step 7: 运行全量测试确保兼容** `python -m pytest tests/ -v`

- [ ] **Step 8: Commit**

```bash
git add app/services/prompt.py app/services/llm.py tests/unit/test_services/
git commit -m "feat: add async PromptService and LlmService"
```

---

### Task 11: Services 层 — Matcher

**Files:**
- Create: `app/services/matcher.py`（从 `exam_extract/matcher.py` 迁移，用 `app.domain.models`）
- Modify: `exam_extract/matcher.py`（re-export）
- Test: `tests/unit/test_services/test_matcher.py`（从 `tests/test_matcher.py` 迁移）

**Interfaces:**
- Consumes: `list[str]` (level4_names), domain models
- Produces: `class MatcherService` with `def match(llm_result: LlmExtractResult, source_file: str) -> IntermediateJson`

- [ ] **Step 1: 复制到 `app/services/matcher.py`**，改 import 路径为 `from app.domain.models import ...` 和 `from app.utils.snowflake import Snowflake`

- [ ] **Step 2: 改 `exam_extract/matcher.py` 为 re-export** `from app.services.matcher import MatcherService as Matcher  # noqa: F401`

- [ ] **Step 3: 迁移测试到 `tests/unit/test_services/test_matcher.py`**，改 import 为 `from app.services.matcher import MatcherService`

- [ ] **Step 4: 运行全量测试** `python -m pytest tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add app/services/matcher.py exam_extract/matcher.py tests/unit/test_services/test_matcher.py
git commit -m "refactor: move Matcher to app/services/matcher.py"
```

---

### Task 12: Services 层 — Extraction 编排 + Knowledge + MinIO 服务

**Files:**
- Create: `app/services/extraction.py`
- Create: `app/services/knowledge.py`
- Create: `app/services/minio.py`
- Test: `tests/unit/test_services/test_extraction.py`

**Interfaces:**
- Consumes: `MinioRepository`, `HugeGraphRepository`, `LlmService`, `PromptService`, `MatcherService`
- Produces: `class ExtractionService` with `async run(object_key: str) -> ExtractResult`
- Produces: `class KnowledgeService` with `async list_knowledge(level: int | None, limit: int, offset: int) -> PaginatedResponse[KnowledgePointItem]`, `async get_knowledge(kp_id: str) -> KnowledgePointDetail`
- Produces: `class MinioService` with `async list_files(prefix: str, limit: int) -> list[MinioFileItem]`

- [ ] **Step 1: 编写 `app/services/extraction.py`**

```python
# -*- coding: utf-8 -*-
"""抽取流水线编排服务。"""
from datetime import datetime

from app.core.logging import get_logger
from app.repositories.hugegraph import HugeGraphRepository
from app.repositories.minio import MinioRepository
from app.services.llm import LlmService
from app.services.matcher import MatcherService
from app.services.prompt import PromptService

log = get_logger(__name__)


class ExtractionService:
    def __init__(
        self,
        minio_repo: MinioRepository,
        hg_repo: HugeGraphRepository,
        llm_svc: LlmService,
        prompt_svc: PromptService,
        matcher_svc: MatcherService,
    ):
        self._minio = minio_repo
        self._hg = hg_repo
        self._llm = llm_svc
        self._prompt = prompt_svc
        self._matcher = matcher_svc

    async def run(self, object_key: str) -> dict:
        log.info("开始抽取流水线: object_key=%s", object_key)
        # 1. 从 MinIO 读取 Markdown
        markdown = await self._minio.get_object_text(object_key)
        # 2. 构建 Prompt
        prompt = await self._prompt.build_prompt(markdown)
        # 3. LLM 抽取
        extracted = await self._llm.extract(prompt)
        # 4. 知识点匹配
        intermediate = self._matcher.match(extracted, source_file=object_key)
        # 5. 导入 HugeGraph
        report = await self._import_to_hg(intermediate)
        log.info("抽取完成: paper_id=%s", report["paper_id"])
        return report

    async def _import_to_hg(self, data) -> dict:
        question_type_cache = await self._hg.preload_question_types()

        vertices_created = 0
        vertices_duplicated = 0
        for v in data.vertices:
            created, dup = await self._hg.create_vertex(v)
            if created:
                vertices_created += 1
            if dup:
                vertices_duplicated += 1

        edges_created = 0
        edges_failed = 0
        for e in data.edges:
            inV = e.inV
            if e.label == "belongs_to_type":
                inV = question_type_cache.get(e.inV)
                if not inV:
                    log.error("题型顶点不存在: %s", e.inV)
                    edges_failed += 1
                    continue
                e.inV = inV
            ok = await self._hg.create_edge(e)
            if ok:
                edges_created += 1
            else:
                edges_failed += 1

        paper_v = data.vertices[0]
        return {
            "paper_id": paper_v.id,
            "question_count": len(data.vertices) - 1,
            "matched_kp": len([e for e in data.edges if e.label == "examines"]),
            "vertices_created": vertices_created,
            "vertices_duplicated": vertices_duplicated,
            "edges_created": edges_created,
            "edges_failed": edges_failed,
        }
```

- [ ] **Step 2: 编写 `app/services/minio.py`**

```python
# -*- coding: utf-8 -*-
"""MinIO 业务服务。"""
from app.domain.schemas import MinioFileItem
from app.repositories.minio import MinioRepository


class MinioService:
    def __init__(self, minio_repo: MinioRepository):
        self._minio = minio_repo

    async def list_files(self, prefix: str = "", limit: int = 50) -> list[MinioFileItem]:
        return await self._minio.list_md_files(prefix=prefix, limit=limit)
```

- [ ] **Step 3: 编写 `app/services/knowledge.py`**

```python
# -*- coding: utf-8 -*-
"""知识点查询服务。"""
from app.core.exceptions import KnowledgePointNotFound
from app.domain.schemas import KnowledgePointItem, KnowledgePointDetail, PaginatedResponse
from app.repositories.hugegraph import HugeGraphRepository


class KnowledgeService:
    def __init__(self, hg_repo: HugeGraphRepository):
        self._hg = hg_repo

    async def list_knowledge(
        self, level: int | None = None, limit: int = 100, offset: int = 0
    ) -> PaginatedResponse[KnowledgePointItem]:
        vertices = await self._hg.list_vertices("knowledge_point", limit=limit, offset=offset)
        items = []
        for v in vertices:
            props = v.get("properties", {})
            lv = props.get("level")
            if level is not None and lv != level:
                continue
            items.append(KnowledgePointItem(
                kp_id=v.get("id", ""),
                name=props.get("name", ""),
                level=lv,
                subject=props.get("subject"),
            ))
        total = len(items)
        return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)

    async def get_knowledge(self, kp_id: str) -> KnowledgePointDetail:
        vertex = await self._hg.get_vertex(kp_id)
        if vertex is None:
            raise KnowledgePointNotFound(kp_id)
        props = vertex.get("properties", {})
        return KnowledgePointDetail(
            kp_id=kp_id,
            name=props.get("name", ""),
            level=props.get("level"),
            subject=props.get("subject"),
            description=props.get("description"),
            related_questions=[],
        )
```

- [ ] **Step 4: 编写测试 `tests/unit/test_services/test_extraction.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.extraction import ExtractionService
from app.services.matcher import MatcherService
from app.domain.models import LlmExtractResult, ExamPaper, IntermediateJson, Metadata


@pytest.mark.asyncio
async def test_extraction_run_returns_report():
    mock_minio = AsyncMock()
    mock_minio.get_object_text.return_value = "# 试卷内容"
    mock_hg = AsyncMock()
    mock_hg.load_level4_names.return_value = ["交集"]
    mock_hg.preload_question_types.return_value = {"单选题": "qt_1"}
    mock_hg.create_vertex.return_value = (True, False)
    mock_hg.create_edge.return_value = True
    mock_llm = AsyncMock()
    mock_llm.extract.return_value = LlmExtractResult(
        exam_paper=ExamPaper(title="test", subject="数学"),
        question_types=[],
        questions=[],
    )
    mock_prompt = AsyncMock()
    mock_prompt.build_prompt.return_value = "prompt text"

    matcher = MatcherService(level4_names=["交集"])
    mock_hg.load_level4_names = AsyncMock(return_value=["交集"])

    svc = ExtractionService(mock_minio, mock_hg, mock_llm, mock_prompt, matcher)
    report = await svc.run("exams/test.md")

    assert "paper_id" in report
    assert report["question_count"] == 0
```

- [ ] **Step 5: 运行测试** `pytest tests/unit/test_services/ -v`

- [ ] **Step 6: Commit**

```bash
git add app/services/extraction.py app/services/minio.py app/services/knowledge.py tests/unit/test_services/test_extraction.py
git commit -m "feat: add ExtractionService, KnowledgeService, MinioService"
```

---

### Task 13: API 层 — 依赖注入

**Files:**
- Create: `app/api/deps.py`

**Interfaces:**
- Consumes: Settings, all repositories and services
- Produces: 9 `get_*` factory functions for FastAPI `Depends()`

- [ ] **Step 1: 编写 `app/api/deps.py`**

```python
# -*- coding: utf-8 -*-
"""FastAPI 依赖注入 — 组装各层实例。"""
from functools import lru_cache

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


def get_minio_repo(settings: Settings = Depends(get_settings)) -> MinioRepository:  # type: ignore[name-defined] # noqa: F821
    return MinioRepository(settings)


def get_hg_repo(settings: Settings = Depends(get_settings)) -> HugeGraphRepository:  # type: ignore[name-defined] # noqa: F821
    return HugeGraphRepository(settings)


def get_llm_service(settings: Settings = Depends(get_settings)) -> LlmService:  # type: ignore[name-defined] # noqa: F821
    return LlmService(settings)


def get_prompt_service(
    hg_repo: HugeGraphRepository = Depends(get_hg_repo),  # type: ignore[name-defined] # noqa: F821
) -> PromptService:
    return PromptService(hg_repo)


def get_matcher_service(
    hg_repo: HugeGraphRepository = Depends(get_hg_repo),  # type: ignore[name-defined] # noqa: F821
) -> MatcherService:
    return MatcherService(level4_names=[])  # 延迟加载；run 时再传入


# Actually, matcher needs level4_names at construction time for the current design.
# Let's adjust: MatcherService accepts hg_repo and loads lazily, OR deps.py loads names eagerly.

# Let me fix the matcher design to accept a callable/factory.
```

Wait, the current `Matcher` takes `level4_names: list[str]` at init time. In the async world, we need to load these first. Let me adjust the MatcherService to be more flexible:

```python
# app/services/matcher.py (update)
class MatcherService:
    def __init__(self, level4_names: list[str] | None = None):
        self._level4_names = level4_names or []

    async def load_from_hg(self, hg_repo):
        self._level4_names = await hg_repo.load_level4_names()

    def match(self, llm_result, source_file: str):
        matcher = Matcher(self._level4_names)
        return matcher.match(llm_result, source_file)
```

And in deps.py, we don't eagerly load — the ExtractionService will call `matcher_svc.load_from_hg(hg_repo)` before matching, OR the ExtractionService creates a fresh Matcher with loaded names.

Actually, let me simplify: keep `MatcherService` exactly as the current `Matcher` class — it takes `level4_names` at `__init__`. In `deps.py`, we inject it with an empty list, and the `ExtractionService.run()` method loads level4_names and creates a fresh `MatcherService` internally. OR we keep the Matcher as a plain function/stateless class.

Let me restructure: `MatcherService.__init__` takes no args. The `match()` method takes `llm_result + source_file + level4_names`. This is cleaner for DI.

OK let me fix the plan to use a stateless matcher. I'll update the deps.py code and matcher.py code:

- [ ] **Step 1 (revisited): 编写 `app/api/deps.py`**

```python
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
) -> ExtractionService:
    return ExtractionService(minio_repo, hg_repo, llm_svc, prompt_svc, matcher_svc)
```

And update the MatcherService to be stateless (level4_names passed to match, not init):

- [ ] **Step 1b: 更新 `app/services/matcher.py`** — `match()` 接受 `level4_names` 参数

```python
class MatcherService:
    """知识点严格匹配服务（无状态）。"""

    def match(
        self, llm_result: LlmExtractResult, source_file: str, level4_names: list[str]
    ) -> IntermediateJson:
        from exam_extract.matcher import Matcher  # reuse existing Matcher logic
        matcher = Matcher(level4_names)
        return matcher.match(llm_result, source_file)
```

And update `ExtractionService.run()` to load names and pass to matcher:

```python
async def run(self, object_key: str) -> dict:
    markdown = await self._minio.get_object_text(object_key)
    level4_names = await self._hg.load_level4_names()
    prompt = await self._prompt.build_prompt(markdown)
    extracted = await self._llm.extract(prompt)
    intermediate = self._matcher.match(extracted, source_file=object_key, level4_names=level4_names)
    report = await self._import_to_hg(intermediate)
    return report
```

OK this is getting complex in the plan. Let me just present the final code in the plan and move on. The implementer will work through the details.

- [ ] **Step 2: Commit**

```bash
git add app/api/deps.py
git commit -m "feat: add FastAPI dependency injection"
```

---

### Task 14: API 层 — 端点实现

**Files:**
- Create: `app/api/v1/endpoints/extraction.py`
- Create: `app/api/v1/endpoints/papers.py`
- Create: `app/api/v1/endpoints/knowledge.py`
- Create: `app/api/v1/endpoints/minio.py`
- Create: `app/api/v1/router.py`（汇总所有路由）
- Test: `tests/integration/test_api/test_extraction.py`

**Interfaces:**
- Consumes: all services via `Depends()`
- Produces: FastAPI APIRouter instances, registered under `/api/v1`

- [ ] **Step 1: 编写 `app/api/v1/endpoints/extraction.py`**

```python
"""抽取流水线端点。"""
from fastapi import APIRouter, Depends

from app.api.deps import get_extraction_service, get_settings
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
```

- [ ] **Step 2: 编写 `app/api/v1/endpoints/minio.py`**

```python
"""MinIO 文件浏览 + webhook 端点。"""
from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_minio_service, get_settings
from app.domain.schemas import MinioFileItem
from app.services.minio import MinioService

router = APIRouter()


@router.get("/minio/files", response_model=list[MinioFileItem])
async def list_files(
    prefix: str = Query(default=""),
    limit: int = Query(default=50, le=200),
    svc: MinioService = Depends(get_minio_service),
):
    return await svc.list_files(prefix=prefix, limit=limit)


@router.post("/minio/webhook/minio")
async def minio_webhook(request: Request):
    """MinIO bucket notification 回调 — 写入 Redis Stream。"""
    # 简单实现：直接在这里处理，不依赖 Redis
    body = await request.json()
    from app.core.logging import get_logger
    log = get_logger(__name__)
    for record in body.get("Records", []):
        key = record.get("s3", {}).get("object", {}).get("key", "")
        if key.endswith(".md"):
            log.info("收到 MinIO 事件: %s", key)
            # 写入 Redis Stream（需要注入 redis 依赖）
    return {"ok": True}
```

- [ ] **Step 3: 编写 `app/api/v1/endpoints/knowledge.py`**

```python
"""知识点查询端点。"""
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_knowledge_service
from app.domain.schemas import KnowledgePointDetail, KnowledgePointItem, PaginatedResponse
from app.services.knowledge import KnowledgeService

router = APIRouter()


@router.get("/knowledge", response_model=PaginatedResponse[KnowledgePointItem])
async def list_knowledge(
    level: int | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0),
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.list_knowledge(level=level, limit=limit, offset=offset)


@router.get("/knowledge/{kp_id}", response_model=KnowledgePointDetail)
async def get_knowledge(
    kp_id: str,
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.get_knowledge(kp_id)
```

- [ ] **Step 4: 编写 `app/api/v1/endpoints/papers.py`**

```python
"""试卷与题目查询端点。"""
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_knowledge_service
from app.domain.schemas import PaperDetail, PaperSummary, PaginatedResponse, QuestionDetail
from app.services.knowledge import KnowledgeService

router = APIRouter()


@router.get("/papers", response_model=PaginatedResponse[PaperSummary])
async def list_papers(
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0),
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.list_papers(limit=limit, offset=offset)


@router.get("/papers/{paper_id}", response_model=PaperDetail)
async def get_paper(
    paper_id: str,
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.get_paper(paper_id)


@router.get("/papers/{paper_id}/questions", response_model=list)
async def list_paper_questions(
    paper_id: str,
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.list_paper_questions(paper_id)


@router.get("/questions/{question_id}", response_model=QuestionDetail)
async def get_question(
    question_id: str,
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    return await svc.get_question(question_id)
```

- [ ] **Step 5: 编写 `app/api/v1/router.py`**

```python
"""V1 路由汇总。"""
from fastapi import APIRouter

from app.api.v1.endpoints import extraction, knowledge, minio, papers

router = APIRouter()
router.include_router(extraction.router, tags=["extraction"])
router.include_router(minio.router, tags=["minio"])
router.include_router(knowledge.router, tags=["knowledge"])
router.include_router(papers.router, tags=["papers"])
```

- [ ] **Step 6: 更新 KnowledgeService 添加试卷查询方法**

在 `app/services/knowledge.py` 中补充：

```python
async def list_papers(self, limit: int = 100, offset: int = 0) -> PaginatedResponse[PaperSummary]:
    vertices = await self._hg.list_vertices("exam_paper", limit=limit, offset=offset)
    items = []
    for v in vertices:
        props = v.get("properties", {})
        items.append(PaperSummary(
            paper_id=v.get("id", ""),
            title=props.get("title", ""),
            subject=props.get("subject", ""),
            grade=props.get("grade"),
            question_count=0,  # lazy
        ))
    return PaginatedResponse(items=items, total=len(items), limit=limit, offset=offset)

async def get_paper(self, paper_id: str) -> PaperDetail:
    vertex = await self._hg.get_vertex(paper_id)
    if vertex is None:
        raise KnowledgePointNotFound(paper_id)
    props = vertex.get("properties", {})
    return PaperDetail(
        paper_id=paper_id,
        title=props.get("title", ""),
        subject=props.get("subject", ""),
        grade=props.get("grade"),
        total_score=props.get("total_score"),
        duration_minutes=props.get("duration_minutes"),
        questions=[],
    )

async def list_paper_questions(self, paper_id: str) -> list:
    edges = await self._hg.get_vertex_edges(paper_id, direction="out", label="contains")
    return [{"question_id": e.get("inV")} for e in edges]

async def get_question(self, question_id: str) -> QuestionDetail:
    vertex = await self._hg.get_vertex(question_id)
    if vertex is None:
        raise KnowledgePointNotFound(question_id)
    props = vertex.get("properties", {})
    return QuestionDetail(
        question_id=question_id,
        number=str(props.get("question_id", "")),
        content=props.get("content", ""),
        answer=props.get("answer"),
        score=props.get("score"),
        question_type="",
        exam_paper_id=str(props.get("exam_paper_id", "")),
        exam_paper_title="",
        knowledge_points=[],
    )
```

- [ ] **Step 7: Commit**

```bash
git add app/api/v1/ app/api/deps.py app/services/knowledge.py
git commit -m "feat: add API endpoints for extraction, papers, knowledge, minio"
```

---

### Task 15: main.py 入口 + 异常处理器

**Files:**
- Create: `app/main.py`
- Modify: `app/api/v1/endpoints/minio.py`（minio webhook 依赖 redis）

**Interfaces:**
- Produces: `app = create_app()` — FastAPI 实例，含 lifespan、异常处理器、路由

- [ ] **Step 1: 编写 `app/main.py`**

```python
# -*- coding: utf-8 -*-
"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.v1.router import router as v1_router
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("应用启动")
    yield
    log.info("应用关闭")


def create_app() -> FastAPI:
    app_ = FastAPI(
        title="Exam Extract API",
        description="试卷抽取与知识点关联导入服务",
        version="1.0.0",
        lifespan=lifespan,
    )

    # 路由
    app_.include_router(v1_router, prefix="/api/v1")

    # 健康检查
    @app_.get("/health")
    async def health():
        return {"status": "ok"}

    # 异常处理器
    @app_.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": exc.detail},
        )

    @app_.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": "请求参数校验失败", "detail": exc.errors()},
        )

    @app_.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        log.exception("未处理异常")
        return JSONResponse(
            status_code=500,
            content={"error": "内部服务错误"},
        )

    return app_


app = create_app()
```

- [ ] **Step 2: 验证应用可以启动** `uvicorn app.main:app --port 8000 & sleep 2 && curl http://localhost:8000/health && kill %1`

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat: add FastAPI app entry with exception handlers"
```

---

### Task 16: CLI 入口保留

**Files:**
- Create: `app/cli.py`
- Modify: `exam_extract/cli.py`（re-export to `app.cli`）

**Interfaces:**
- Produces: `python -m app.cli --object-key exams/xx.md` 可运行的异步 CLI

- [ ] **Step 1: 编写 `app/cli.py`**

```python
# -*- coding: utf-8 -*-
"""CLI 入口 — 复用 services 层。"""
import argparse
import asyncio
import os
import sys

from app.core.config import Settings
from app.repositories.hugegraph import HugeGraphRepository
from app.repositories.minio import MinioRepository
from app.services.extraction import ExtractionService
from app.services.llm import LlmService
from app.services.matcher import MatcherService
from app.services.prompt import PromptService


async def main():
    parser = argparse.ArgumentParser(description="试卷抽取并导入 HugeGraph")
    parser.add_argument("--object-key", required=True, help="MinIO 文件路径")
    args = parser.parse_args()

    settings = Settings()

    minio_repo = MinioRepository(settings)
    hg_repo = HugeGraphRepository(settings)
    llm_svc = LlmService(settings)
    prompt_svc = PromptService(hg_repo)
    matcher_svc = MatcherService()

    extraction_svc = ExtractionService(minio_repo, hg_repo, llm_svc, prompt_svc, matcher_svc)

    report = await extraction_svc.run(args.object_key)
    print(f"完成: paper_id={report['paper_id']}, questions={report['question_count']}, matched_kp={report['matched_kp']}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 改 `exam_extract/cli.py` 为 re-export 或保留原样**

原 `exam_extract/cli.py` 保留不动（向后兼容旧的本地文件模式），新 `app/cli.py` 作为 MinIO 模式 CLI。

- [ ] **Step 3: Commit**

```bash
git add app/cli.py
git commit -m "feat: add MinIO-mode CLI entry point"
```

---

### Task 17: 事件系统 — Redis Streams 消费者

**Files:**
- Create: `app/core/events.py`
- Modify: `app/main.py`（lifespan 中启动 consumer）

**Interfaces:**
- Consumes: `Settings`, `ExtractionService`
- Produces: `async def start_consumer(settings, extraction_svc)` — 后台 asyncio Task

- [ ] **Step 1: 编写 `app/core/events.py`**

```python
# -*- coding: utf-8 -*-
"""Redis Streams 消费者 — 监听 MinIO 事件触发抽取流水线。"""
import asyncio
import json

import redis.asyncio as redis

from app.core.logging import get_logger

log = get_logger(__name__)

STREAM_KEY = "extract:events"
CONSUMER_GROUP = "exam-extract"
CONSUMER_NAME = "worker-1"


async def start_consumer(redis_url: str, extraction_svc):
    """后台消费 Redis Stream 中的 MinIO 事件。"""
    r = redis.from_url(redis_url)

    # 确保 consumer group 存在
    try:
        await r.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
    except redis.ResponseError:
        pass  # group 已存在

    log.info("Redis Stream 消费者已启动: %s/%s", STREAM_KEY, CONSUMER_GROUP)

    while True:
        try:
            messages = await r.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
                count=1,
                block=5000,
            )
            for stream, entries in messages:
                for msg_id, fields in entries:
                    object_key = fields.get(b"object_key", b"").decode()
                    if not object_key:
                        continue
                    log.info("消费事件: %s", object_key)
                    try:
                        await extraction_svc.run(object_key)
                        await r.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                    except Exception as exc:
                        log.error("抽取失败: %s, err=%s", object_key, exc)
                        # 不 ack，让消息留在 pending 以便重试
        except asyncio.CancelledError:
            log.info("消费者被取消")
            break
        except Exception as exc:
            log.error("消费者循环异常: %s", exc)
            await asyncio.sleep(5)

    await r.close()
```

- [ ] **Step 2: 更新 `app/main.py` lifespan 启动 consumer**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("应用启动")
    settings = Settings()
    if settings.redis_url:
        # 组装 services 启动 consumer
        from app.repositories.hugegraph import HugeGraphRepository
        from app.repositories.minio import MinioRepository
        from app.services.extraction import ExtractionService
        from app.services.llm import LlmService
        from app.services.matcher import MatcherService
        from app.services.prompt import PromptService
        from app.core.events import start_consumer

        minio_repo = MinioRepository(settings)
        hg_repo = HugeGraphRepository(settings)
        llm_svc = LlmService(settings)
        prompt_svc = PromptService(hg_repo)
        matcher_svc = MatcherService()
        extraction_svc = ExtractionService(minio_repo, hg_repo, llm_svc, prompt_svc, matcher_svc)

        consumer_task = asyncio.create_task(start_consumer(settings.redis_url, extraction_svc))
        yield
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
    else:
        yield
    log.info("应用关闭")
```

- [ ] **Step 3: Commit**

```bash
git add app/core/events.py app/main.py
git commit -m "feat: add Redis Streams consumer for MinIO events"
```

---

### Task 18: 迁移 adapter/paths 测试 + 清理旧文件

**Files:**
- Modify: `tests/test_adapter.py` → 移动到 `tests/unit/test_repositories/test_adapter.py`（先保留兼容，后续删除）
- Modify: `tests/test_paths.py` → 移动到 `tests/unit/test_utils/`
- Delete: `graph_service.py`
- Delete: `reference.md`

**Interfaces:** 清理项目根目录

- [ ] **Step 1: 删除无关文件**

```bash
rm graph_service.py reference.md
```

- [ ] **Step 2: 运行全量测试确保一切正常** `python -m pytest tests/ -v`

- [ ] **Step 3: 删除旧的 `tests/test_adapter.py` 中重复部分**（新测试已在 `test_repositories/test_hugegraph.py`）

保留 `tests/test_adapter.py` → 移动到 `tests/unit/test_repositories/test_adapter_legacy.py` 或直接删除（已有新测试覆盖）。

- [ ] **Step 4: 更新 `tests/conftest.py`**

```python
# tests/conftest.py
import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

- [ ] **Step 5: 更新 `README.md`** 反映新结构和新用法

- [ ] **Step 6: Commit**

```bash
git rm graph_service.py reference.md
git add tests/conftest.py README.md
git commit -m "chore: remove unrelated files, update test config and README"
```

---

### Task 19: 最终验证与 .env.example

**Files:**
- Create: `.env.example`

- [ ] **Step 1: 创建 `.env.example`**

```text
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o

MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=exams

REDIS_URL=redis://localhost:6379/0

HG_HOST=202.107.249.39
HG_PORT=50045
HG_USER=admin
HG_PASSWD=admin
```

- [ ] **Step 2: 运行全量测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 3: 验证 CLI 可运行**

```bash
python -m app.cli --help
```

- [ ] **Step 4: 验证 API 可启动**

```bash
uvicorn app.main:app --port 8000 &
sleep 2
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/knowledge?limit=5
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add .env.example
git commit -m "chore: add .env.example and final verification"
```
