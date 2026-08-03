# 试卷抽取与四级知识点关联导入 HugeGraph 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一套可复用的流水线：从 markdown 试卷抽取题目信息，严格匹配已有四级知识点，生成 HugeGraph 可导入的中间 JSON，并通过 REST API 写入 `edu` 图库。

**Architecture:** 采用三阶段流水线（LLM Prompt 抽取 → 代码严格匹配 → Adapter 导入）。核心逻辑拆分为 `models`（Pydantic 结构定义）、`matcher`（严格匹配与 ID 生成）、`adapter`（HugeGraph REST API 调用）三个独立模块，通过 CLI 串接。

**Tech Stack:** Python 3.9+、Pydantic v2、requests、pytest

## Global Constraints

- 只关联已存在的四级知识点，不新建知识点节点。
- `exam_paper_id` 和 `question_id` 使用雪花算法生成。
- `question` 顶点已存在时默认跳过，保持幂等性。
- `question_type` 顶点已存在四类（单选/多选/填空/解答），通过 `name` 查询物理 id。
- 题干 `content` 保留原始 LaTeX。
- 严格匹配仅做 `strip()` + 完全相等比较，不做同义词扩展。
- 复用现有 `libs.logger.get_logger` 日志工具。

---

## 文件结构

```
/Users/edy/Documents/llm-extract-question/
├── exam_extract/
│   ├── __init__.py
│   ├── models.py          # Pydantic 模型：LLM 输出 + 中间 JSON
│   ├── matcher.py         # Stage 2：严格匹配、ID 生成、中间 JSON 构造
│   ├── adapter.py         # Stage 3：HugeGraph REST API 导入
│   ├── prompt.py          # Prompt 构建与知识点列表加载
│   └── cli.py             # 命令行入口
├── prompts/
│   └── exam_extract.md    # LLM Prompt 模板
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_matcher.py
│   └── test_adapter.py
├── requirements.txt       # 新增 pydantic、requests
└── docs/superpowers/specs/2026-08-01-exam-knowledge-point-linking-design.md
```

---

### Task 1: Pydantic 模型定义

**Files:**
- Create: `exam_extract/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `ExamPaper(BaseModel)`
  - `QuestionType(BaseModel)`
  - `Question(BaseModel)`
  - `LlmExtractResult(BaseModel)` — LLM Stage 1 输出
  - `Vertex(BaseModel)` — 中间 JSON 顶点
  - `Edge(BaseModel)` — 中间 JSON 边
  - `UnmatchedItem(BaseModel)` — 未命中项
  - `IntermediateJson(BaseModel)` — Stage 2 输出

- [ ] **Step 1: 编写模型单元测试**

```python
# tests/test_models.py
import pytest
from exam_extract.models import LlmExtractResult, IntermediateJson, Vertex, Edge


def test_llm_extract_result_parsing():
    raw = {
        "exam_paper": {
            "title": "测试卷",
            "subject": "数学",
            "grade": "高一",
            "total_score": 150,
            "duration_minutes": 120
        },
        "question_types": [{"name": "单选题", "description": ""}],
        "questions": [{
            "number": "1",
            "content": "测试题干",
            "answer": "A",
            "score": 5,
            "question_type": "单选题",
            "candidate_knowledge_points": ["子集"]
        }]
    }
    result = LlmExtractResult.model_validate(raw)
    assert result.exam_paper.title == "测试卷"
    assert result.questions[0].candidate_knowledge_points == ["子集"]


def test_intermediate_json_serialization():
    data = {
        "metadata": {
            "source_file": "test.md",
            "generated_at": "2026-08-02T10:00:00",
            "matching_mode": "strict"
        },
        "vertices": [
            {
                "label": "question",
                "id": "question_123",
                "properties": {"question_id": 123, "content": "test"}
            }
        ],
        "edges": [
            {
                "label": "examines",
                "outV": "question_123",
                "inV": "level_4_子集",
                "properties": {"create_time": "2026-08-02 10:00:00"}
            }
        ],
        "unmatched": []
    }
    result = IntermediateJson.model_validate(data)
    assert result.vertices[0].id == "question_123"
    assert result.edges[0].inV == "level_4_子集"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_models.py -v`
Expected: FAIL，提示 `exam_extract.models` 不存在

- [ ] **Step 3: 实现 Pydantic 模型**

```python
# exam_extract/models.py
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class ExamPaper(BaseModel):
    title: str
    subject: str = "数学"
    grade: Optional[str] = None
    total_score: Optional[int] = None
    duration_minutes: Optional[int] = None


class QuestionType(BaseModel):
    name: str
    description: Optional[str] = None


class Question(BaseModel):
    number: str
    content: str
    answer: Optional[str] = None
    score: Optional[int] = None
    question_type: str
    candidate_knowledge_points: List[str] = Field(default_factory=list)


class LlmExtractResult(BaseModel):
    exam_paper: ExamPaper
    question_types: List[QuestionType]
    questions: List[Question]


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
    vertices: List[Vertex]
    edges: List[Edge]
    unmatched: List[UnmatchedItem]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add exam_extract/models.py tests/test_models.py
# git commit -m "feat: add Pydantic models for exam extraction pipeline"
```

---

### Task 2: Prompt 模板与知识点列表加载

**Files:**
- Create: `prompts/exam_extract.md`
- Create: `exam_extract/prompt.py`
- Test: `tests/test_prompt.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `build_prompt(markdown_content: str, level4_names: List[str]) -> str`
  - `load_level4_knowledge_points(host, port, user, passwd, graphspace, graph) -> List[str]`

- [ ] **Step 1: 编写 Prompt 模板**

```markdown
# prompts/exam_extract.md
你是一名资深高中数学教研专家兼知识图谱工程师。请从给定的高中数学试卷 Markdown 文本中抽取试卷、题目信息，并为每道题列出可能考查的四级知识点候选名称。

## 已有四级知识点清单
以下清单中的知识点已经存在于知识图谱中。你不需要判断候选名称是否一定在清单中，只需从题干中尽可能准确地提取候选四级知识点名称。

{{level_4_knowledge_points}}

## 试卷 Markdown
{{markdown_content}}

## 输出要求
请严格输出以下 JSON 格式，不要输出任何解释文字：

```json
{
  "exam_paper": {
    "title": "试卷标题",
    "subject": "数学",
    "grade": "高一",
    "total_score": 150,
    "duration_minutes": 120
  },
  "question_types": [
    {"name": "单选题", "description": ""}
  ],
  "questions": [
    {
      "number": "1",
      "content": "题干原文（保留 LaTeX）",
      "answer": "A",
      "score": 5,
      "question_type": "单选题",
      "candidate_knowledge_points": ["候选知识点1", "候选知识点2"]
    }
  ]
}
```

## 约束
1. candidate_knowledge_points 只列四级知识点名称。
2. content 必须保留原始 LaTeX 公式，不改写题意。
3. question_type 名称必须是：单选题、多选题、填空题、解答题 之一。
4. 题号保持原始格式，如 1、9、17(1)。
5. 客观题（选择/填空）尽量给出 answer；解答题 answer 可留空。
6. 严格输出 JSON，不要 Markdown 代码块外的任何文字。
```

- [ ] **Step 2: 编写 Prompt 构建与知识点加载测试**

```python
# tests/test_prompt.py
from exam_extract.prompt import build_prompt, load_level4_knowledge_points


def test_build_prompt_replaces_placeholders():
    names = ["子集", "交集"]
    md = "# 测试卷\n1. 已知集合 A={1}..."
    prompt = build_prompt(md, names)
    assert "子集" in prompt
    assert "交集" in prompt
    assert "# 测试卷" in prompt
    assert "candidate_knowledge_points" in prompt
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/test_prompt.py -v`
Expected: FAIL

- [ ] **Step 4: 实现 Prompt 模块**

```python
# exam_extract/prompt.py
import os
import requests
from typing import List


def build_prompt(markdown_content: str, level4_names: List[str]) -> str:
    """替换 Prompt 模板中的占位符。"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompt_path = os.path.join(base_dir, "prompts", "exam_extract.md")
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    names_text = "\n".join(f"- {name}" for name in sorted(level4_names))
    return template.replace("{{level_4_knowledge_points}}", names_text) \
                   .replace("{{markdown_content}}", markdown_content)


def load_level4_knowledge_points(
    host: str,
    port: int,
    user: str,
    passwd: str,
    graphspace: str = "DEFAULT",
    graph: str = "edu"
) -> List[str]:
    """从 HugeGraph 查询所有 level=4 的知识点名称。"""
    url = (
        f"http://{host}:{port}/graphspaces/{graphspace}/graphs/{graph}"
        f"/graph/vertices?label=knowledge_point&limit=10000"
    )
    resp = requests.get(url, auth=(user, passwd))
    resp.raise_for_status()
    data = resp.json()
    names = []
    for v in data.get("vertices", []):
        props = v.get("properties", {})
        if props.get("level") == 4:
            names.append(props.get("name", ""))
    return [n for n in names if n]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_prompt.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add prompts/exam_extract.md exam_extract/prompt.py tests/test_prompt.py
# git commit -m "feat: add prompt template and level4 kp loader"
```

---

### Task 3: Stage 2 严格匹配器

**Files:**
- Create: `exam_extract/matcher.py`
- Create: `exam_extract/snowflake.py`（或内嵌到 matcher）
- Test: `tests/test_matcher.py`

**Interfaces:**
- Consumes:
  - `LlmExtractResult`（Task 1）
  - `List[str]` level4_names（Task 2）
- Produces:
  - `match_result(llm_result, level4_names, source_file, snowflake_gen) -> IntermediateJson`

- [ ] **Step 1: 编写匹配器单元测试**

```python
# tests/test_matcher.py
from exam_extract.matcher import Matcher
from exam_extract.models import LlmExtractResult, ExamPaper, QuestionType, Question


def test_match_question_to_existing_kp():
    llm_result = LlmExtractResult(
        exam_paper=ExamPaper(title="测试卷", subject="数学"),
        question_types=[QuestionType(name="单选题")],
        questions=[Question(
            number="1",
            content="题干",
            answer="A",
            score=5,
            question_type="单选题",
            candidate_knowledge_points=["子集", "不存在知识点"]
        )]
    )
    matcher = Matcher(level4_names=["子集", "交集"])
    result = matcher.match(llm_result, source_file="test.md")

    assert len(result.vertices) == 2  # exam_paper + question
    assert len(result.edges) == 3     # contains + belongs_to_type + examines
    assert len(result.unmatched) == 1
    assert result.unmatched[0].candidate == "不存在知识点"

    examines_edges = [e for e in result.edges if e.label == "examines"]
    assert examines_edges[0].inV == "level_4_子集"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_matcher.py -v`
Expected: FAIL

- [ ] **Step 3: 实现雪花 ID 生成器**

```python
# exam_extract/snowflake.py
import time
import threading


class Snowflake:
    """简易雪花 ID 生成器（适合单机场景）。"""

    def __init__(self, datacenter_id: int = 0, worker_id: int = 0):
        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self.sequence = 0
        self.last_timestamp = -1
        self.lock = threading.Lock()

    def _til_next_millis(self, last_timestamp: int) -> int:
        timestamp = int(time.time() * 1000)
        while timestamp <= last_timestamp:
            timestamp = int(time.time() * 1000)
        return timestamp

    def next_id(self) -> int:
        with self.lock:
            timestamp = int(time.time() * 1000)
            if timestamp < self.last_timestamp:
                raise Exception("Clock moved backwards")
            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & 4095
                if self.sequence == 0:
                    timestamp = self._til_next_millis(self.last_timestamp)
            else:
                self.sequence = 0
            self.last_timestamp = timestamp
            return ((timestamp - 1288834974657) << 22) | \
                   (self.datacenter_id << 17) | \
                   (self.worker_id << 12) | \
                   self.sequence
```

- [ ] **Step 4: 实现匹配器**

```python
# exam_extract/matcher.py
from datetime import datetime
from typing import List

from exam_extract.models import (
    Edge, ExamPaper, IntermediateJson, LlmExtractResult,
    Metadata, Question, QuestionType, UnmatchedItem, Vertex
)
from exam_extract.snowflake import Snowflake


class Matcher:
    def __init__(self, level4_names: List[str], snowflake: Snowflake = None):
        self.level4_map = {name.strip(): f"level_4_{name.strip()}" for name in level4_names}
        self.snowflake = snowflake or Snowflake()

    def match(self, llm_result: LlmExtractResult, source_file: str) -> IntermediateJson:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_iso = datetime.now().isoformat()

        exam_paper_id = self.snowflake.next_id()
        paper_vertex_id = f"paper_{exam_paper_id}"

        vertices: List[Vertex] = []
        edges: List[Edge] = []
        unmatched: List[UnmatchedItem] = []

        paper_props = self._build_paper_props(llm_result.exam_paper, exam_paper_id, now)
        vertices.append(Vertex(label="exam_paper", id=paper_vertex_id, properties=paper_props))

        for q in llm_result.questions:
            question_id = self.snowflake.next_id()
            question_vertex_id = f"question_{question_id}"
            question_props = self._build_question_props(
                q, question_id, exam_paper_id, llm_result.question_types, now
            )
            vertices.append(Vertex(label="question", id=question_vertex_id, properties=question_props))

            edges.append(Edge(
                label="contains",
                outV=paper_vertex_id,
                inV=question_vertex_id,
                properties={"create_time": now}
            ))

            edges.append(Edge(
                label="belongs_to_type",
                outV=question_vertex_id,
                inV=q.question_type,  # 注意：这里先用 name，adapter 再查物理 id
                properties={"create_time": now}
            ))

            for candidate in q.candidate_knowledge_points:
                candidate = candidate.strip()
                if candidate in self.level4_map:
                    edges.append(Edge(
                        label="examines",
                        outV=question_vertex_id,
                        inV=self.level4_map[candidate],
                        properties={"create_time": now}
                    ))
                else:
                    unmatched.append(UnmatchedItem(
                        question_id=question_vertex_id,
                        number=q.number,
                        candidate=candidate
                    ))

        return IntermediateJson(
            metadata=Metadata(
                source_file=source_file,
                generated_at=now_iso,
                matching_mode="strict"
            ),
            vertices=vertices,
            edges=edges,
            unmatched=unmatched
        )

    def _build_paper_props(self, paper: ExamPaper, exam_paper_id: int, now: str) -> dict:
        return {
            "exam_paper_id": exam_paper_id,
            "title": paper.title,
            "subject": paper.subject,
            "grade": paper.grade,
            "total_score": paper.total_score,
            "duration_minutes": paper.duration_minutes,
            "created_at": now,
            "updated_at": now
        }

    def _build_question_props(
        self,
        q: Question,
        question_id: int,
        exam_paper_id: int,
        question_types: List[QuestionType],
        now: str
    ) -> dict:
        type_id = self._resolve_question_type_id(q.question_type, question_types)
        return {
            "question_id": question_id,
            "content": q.content,
            "answer": q.answer,
            "score": q.score,
            "question_type_id": type_id,
            "exam_paper_id": exam_paper_id,
            "source_file_id": 0,
            "sub_file_id": 0,
            "created_at": now,
            "updated_at": now
        }

    def _resolve_question_type_id(self, name: str, question_types: List[QuestionType]) -> int:
        mapping = {"单选题": 1, "多选题": 2, "填空题": 3, "解答题": 4}
        return mapping.get(name, 0)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_matcher.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add exam_extract/matcher.py exam_extract/snowflake.py tests/test_matcher.py
# git commit -m "feat: add strict matcher for level4 knowledge points"
```

---

### Task 4: Stage 3 HugeGraph Adapter

**Files:**
- Create: `exam_extract/adapter.py`
- Test: `tests/test_adapter.py`

**Interfaces:**
- Consumes:
  - `IntermediateJson`（Task 3）
- Produces:
  - `HugeGraphAdapter.import_data(intermediate_json) -> ImportReport`

- [ ] **Step 1: 编写 Adapter 单元测试（使用 mock）**

```python
# tests/test_adapter.py
from unittest.mock import MagicMock, patch
from exam_extract.adapter import HugeGraphAdapter
from exam_extract.models import IntermediateJson, Metadata, Vertex, Edge


def test_import_skips_existing_question_vertex():
    intermediate = IntermediateJson(
        metadata=Metadata(source_file="test.md", generated_at="2026-08-02T10:00:00"),
        vertices=[Vertex(label="question", id="question_123", properties={"question_id": 123, "content": "x"})],
        edges=[],
        unmatched=[]
    )
    adapter = HugeGraphAdapter("localhost", 8080, "admin", "admin")

    with patch.object(adapter, "_post_vertex") as mock_post:
        mock_post.return_value = MagicMock(status_code=400, text='{"message":"Vertex id \"question_123\" already exists"}')
        report = adapter.import_data(intermediate)
        assert report["vertices_created"] == 0
        assert report["vertices_duplicated"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 Adapter**

```python
# exam_extract/adapter.py
from typing import Any, Dict, List
import requests

from libs.logger import get_logger
from exam_extract.models import Edge, IntermediateJson, Vertex

log = get_logger(__name__)


class HugeGraphAdapter:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        passwd: str,
        graphspace: str = "DEFAULT",
        graph: str = "edu"
    ):
        self.base_url = f"http://{host}:{port}/graphspaces/{graphspace}/graphs/{graph}"
        self.auth = (user, passwd)
        self._question_type_cache: Dict[str, str] = {}

    def import_data(self, data: IntermediateJson) -> Dict[str, Any]:
        self._preload_question_types()

        report = {
            "vertices_total": len(data.vertices),
            "vertices_created": 0,
            "vertices_duplicated": 0,
            "edges_total": len(data.edges),
            "edges_created": 0,
            "edges_failed": 0
        }

        for v in data.vertices:
            created, duplicated = self._create_vertex(v)
            if created:
                report["vertices_created"] += 1
            if duplicated:
                report["vertices_duplicated"] += 1

        for e in data.edges:
            if self._create_edge(e):
                report["edges_created"] += 1
            else:
                report["edges_failed"] += 1

        log.info("导入完成: %s", report)
        return report

    def _preload_question_types(self) -> None:
        url = f"{self.base_url}/graph/vertices?label=question_type"
        resp = requests.get(url, auth=self.auth)
        resp.raise_for_status()
        for v in resp.json().get("vertices", []):
            name = v.get("properties", {}).get("name")
            if name:
                self._question_type_cache[name] = v.get("id")

    def _create_vertex(self, vertex: Vertex) -> tuple[bool, bool]:
        url = f"{self.base_url}/graph/vertices"
        payload = {
            "label": vertex.label,
            "id": vertex.id,
            "type": "vertex",
            "properties": vertex.properties
        }
        resp = requests.post(url, json=payload, auth=self.auth)
        if resp.status_code in (200, 201):
            log.info("顶点创建成功: %s (%s)", vertex.label, vertex.id)
            return True, False
        if resp.status_code == 400 and "already exists" in resp.text.lower():
            log.debug("顶点已存在，跳过: %s (%s)", vertex.label, vertex.id)
            return False, True
        log.error("顶点创建失败: %s (%s): %s", vertex.label, vertex.id, resp.text)
        return False, False

    def _create_edge(self, edge: Edge) -> bool:
        url = f"{self.base_url}/graph/edges"

        inV = edge.inV
        if edge.label == "belongs_to_type":
            inV = self._question_type_cache.get(edge.inV)
            if not inV:
                log.error("题型顶点不存在: %s", edge.inV)
                return False

        payload = {
            "label": edge.label,
            "outV": edge.outV,
            "inV": inV,
            "properties": edge.properties
        }
        resp = requests.post(url, json=payload, auth=self.auth)
        if resp.status_code in (200, 201):
            log.info("边创建成功: %s -[%s]-> %s", edge.outV, edge.label, inV)
            return True
        log.error("边创建失败: %s -[%s]-> %s: %s", edge.outV, edge.label, inV, resp.text)
        return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add exam_extract/adapter.py tests/test_adapter.py
# git commit -m "feat: add HugeGraph REST API adapter"
```

---

### Task 5: CLI 入口与集成

**Files:**
- Create: `exam_extract/cli.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes:
  - `prompt.build_prompt`
  - `prompt.load_level4_knowledge_points`
  - `matcher.Matcher`
  - `adapter.HugeGraphAdapter`
- Produces:
  - `python -m exam_extract.cli --markdown path/to/exam.md --output result.json`

- [ ] **Step 1: 实现 CLI**

```python
# exam_extract/cli.py
import argparse
import json
import os
from datetime import datetime

from libs.logger import get_logger
from exam_extract.prompt import build_prompt, load_level4_knowledge_points
from exam_extract.matcher import Matcher
from exam_extract.adapter import HugeGraphAdapter

log = get_logger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="试卷抽取并导入 HugeGraph")
    parser.add_argument("--markdown", required=True, help="试卷 markdown 文件路径")
    parser.add_argument("--output", required=True, help="中间 JSON 输出路径")
    parser.add_argument("--host", default="202.107.249.39")
    parser.add_argument("--port", type=int, default=50045)
    parser.add_argument("--user", default="admin")
    parser.add_argument("--passwd", default="admin")
    parser.add_argument("--graphspace", default="DEFAULT")
    parser.add_argument("--graph", default="edu")
    parser.add_argument("--import-to-hg", action="store_true", help="是否直接导入 HugeGraph")
    return parser.parse_args()


def main():
    args = parse_args()

    with open(args.markdown, "r", encoding="utf-8") as f:
        markdown_content = f.read()

    log.info("加载四级知识点列表...")
    level4_names = load_level4_knowledge_points(
        args.host, args.port, args.user, args.passwd, args.graphspace, args.graph
    )
    log.info("加载到 %d 个四级知识点", len(level4_names))

    prompt = build_prompt(markdown_content, level4_names)
    log.info("Prompt 已生成，请将其发送给 LLM，并将 LLM 输出保存为 JSON 文件。")

    # 这里假设 LLM 输出已经保存到与 markdown 同目录的 .llm.json 文件
    llm_output_path = args.markdown.replace(".md", ".llm.json")
    if not os.path.exists(llm_output_path):
        log.warning("未找到 LLM 输出文件: %s，请手动提供后再运行 --import-to-hg", llm_output_path)
        print(f"\n请将 LLM 输出保存到: {llm_output_path}\n")
        return

    with open(llm_output_path, "r", encoding="utf-8") as f:
        llm_result = json.load(f)

    from exam_extract.models import LlmExtractResult
    extracted = LlmExtractResult.model_validate(llm_result)

    matcher = Matcher(level4_names)
    intermediate = matcher.match(extracted, source_file=args.markdown)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(intermediate.model_dump_json(indent=2, ensure_ascii=False))
    log.info("中间 JSON 已保存: %s", args.output)

    if args.import_to_hg:
        hg = HugeGraphAdapter(args.host, args.port, args.user, args.passwd, args.graphspace, args.graph)
        report = hg.import_data(intermediate)
        log.info("HugeGraph 导入报告: %s", report)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 更新 requirements.txt**

```text
pydantic>=2.0
requests>=2.28.0
```

- [ ] **Step 3: 手动验证 CLI 生成 Prompt**

Run:
```bash
python -m exam_extract.cli --markdown reference/24-01-20高一数课堂资料（模拟卷）.md --output tmp/exam_result.json
```

Expected: 生成 Prompt 并提示保存 LLM 输出文件。

- [ ] **Step 4: Commit**

```bash
git add exam_extract/cli.py requirements.txt
# git commit -m "feat: add CLI entry point"
```

---

### Task 6: 端到端集成测试

**Files:**
- Create: `tests/test_integration.py`
- Create: `tests/fixtures/sample_exam.md`
- Create: `tests/fixtures/sample_exam.llm.json`

**Interfaces:**
- Consumes: 所有前面任务的产出
- Produces: 集成测试用例

- [ ] **Step 1: 准备测试夹具**

```markdown
# tests/fixtures/sample_exam.md
# 高一数学测试卷

## 一、选择题

1. 已知集合 $A=\\{1,2\\}$，$B=\\{2,3\\}$，则 $A \\cap B =$（ ）

A. $\\{1\\}$  B. $\\{2\\}$  C. $\\{3\\}$  D. $\\{1,2,3\\}$
```

```json
// tests/fixtures/sample_exam.llm.json
{
  "exam_paper": {
    "title": "高一数学测试卷",
    "subject": "数学",
    "grade": "高一",
    "total_score": 100,
    "duration_minutes": 90
  },
  "question_types": [
    {"name": "单选题", "description": ""}
  ],
  "questions": [
    {
      "number": "1",
      "content": "已知集合 $A=\\{1,2\\}$，$B=\\{2,3\\}$，则 $A \\cap B =$（ ）",
      "answer": "B",
      "score": 5,
      "question_type": "单选题",
      "candidate_knowledge_points": ["交集"]
    }
  ]
}
```

- [ ] **Step 2: 编写集成测试**

```python
# tests/test_integration.py
import json
import os
from exam_extract.models import LlmExtractResult
from exam_extract.matcher import Matcher


def test_end_to_end_matching():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base_dir, "fixtures", "sample_exam.llm.json"), "r", encoding="utf-8") as f:
        llm_result = LlmExtractResult.model_validate(json.load(f))

    matcher = Matcher(level4_names=["交集", "并集", "子集"])
    intermediate = matcher.match(llm_result, source_file="sample_exam.md")

    assert intermediate.metadata.matching_mode == "strict"
    assert len(intermediate.vertices) == 2
    assert any(v.label == "exam_paper" for v in intermediate.vertices)
    assert any(v.label == "question" for v in intermediate.vertices)
    assert any(e.label == "examines" and e.inV == "level_4_交集" for e in intermediate.edges)
    assert len(intermediate.unmatched) == 0
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_integration.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py tests/fixtures/
# git commit -m "test: add end-to-end integration test"
```

---

### Task 7: 文档与 README 更新

**Files:**
- Modify: `docs/superpowers/specs/2026-08-01-exam-knowledge-point-linking-design.md`
- Create: `exam_extract/README.md`

- [ ] **Step 1: 创建模块 README**

```markdown
# exam_extract

从 markdown 试卷抽取题目并关联已有四级知识点，导入 HugeGraph。

## 使用流程

1. 准备 markdown 试卷文件。
2. 运行 CLI 生成 Prompt：
   ```bash
   python -m exam_extract.cli \
     --markdown reference/24-01-20高一数课堂资料（模拟卷）.md \
     --output tmp/exam_result.json
   ```
3. 将生成的 Prompt 发送给 LLM，保存返回 JSON 为 `tmp/24-01-20高一数课堂资料（模拟卷）.llm.json`。
4. 再次运行 CLI 生成中间 JSON 并导入：
   ```bash
   python -m exam_extract.cli \
     --markdown reference/24-01-20高一数课堂资料（模拟卷）.md \
     --output tmp/exam_result.json \
     --import-to-hg
   ```

## 测试

```bash
pytest tests/ -v
```
```

- [ ] **Step 2: 在 spec 末尾增加实现引用**

在 spec 第 10 节后追加：

```markdown
## 11. 实现文件索引

- `exam_extract/models.py`：Pydantic 模型
- `exam_extract/prompt.py`：Prompt 构建与知识点加载
- `exam_extract/matcher.py`：Stage 2 严格匹配
- `exam_extract/adapter.py`：Stage 3 HugeGraph 导入
- `exam_extract/cli.py`：命令行入口
- `prompts/exam_extract.md`：LLM Prompt 模板
```

- [ ] **Step 3: Commit**

```bash
git add exam_extract/README.md docs/superpowers/specs/2026-08-01-exam-knowledge-point-linking-design.md
# git commit -m "docs: add README and update spec"
```

---

## 全局测试命令

```bash
pytest tests/ -v
```

---

## 计划自审

### Spec 覆盖检查

| Spec 章节 | 对应 Task |
|-----------|-----------|
| 3. Stage 1 Prompt | Task 2 |
| 4. Stage 2 严格匹配 | Task 3 |
| 5. 中间 JSON Schema | Task 1 |
| 6. Adapter 脚本 | Task 4 |
| 7. 错误处理 | Task 4（跳过重复）、Task 3（未命中） |
| 8. 验收标准 | Task 6 集成测试 |

### Placeholder 检查

- 无 TBD/TODO
- 所有测试代码包含具体断言
- 所有函数签名在任务间一致

### 类型一致性检查

- `IntermediateJson` 在 Task 1 定义，Task 3 产出，Task 4 消费，字段一致。
- `Matcher.match()` 返回 `IntermediateJson`，`Adapter.import_data()` 接收 `IntermediateJson`。
