# 试卷抽取与四级知识点关联导入 HugeGraph 设计文档

> 状态：待实现  
> 作者：Claude Code  
> 日期：2026-08-01  
> 关联文件：`reference/SCHEMA.md`、`reference/education_kg_schema(1).groovy`、`reference/schema(1).json`

---

## 1. 背景与目标

### 1.1 背景

当前 `edu` 图库已存在完整的高中数学教育知识图谱 Schema，包含：

- **7 类顶点**：`knowledge_point`、`question`、`exam_paper`、`question_type`、`solution`、`formula_theorem`、`error_prone`
- **9 类边**：`examines`、`contains`、`belongs_to_type`、`solved_by`、`uses_formula`、`prone_to_error`、`variant_of`、`contains_kp`、`related_kp`
- **28 个属性键**、**8 个索引**
- 当前数据规模：`knowledge_point` 顶点 970 个，其中 **四级知识点 591 个**

四级知识点 ID 策略为 `CUSTOMIZE_STRING`，物理 id 格式为：

```text
level_4_{name}
```

例如：`level_4_子集`、`level_4_指数函数的性质`。

### 1.2 目标

设计一套可复用的流程，将新的 markdown 试卷文件：

1. 抽取为题目实体（`question`、`exam_paper`、`question_type`）；
2. 将每道题关联到**已有**的四级知识点（`knowledge_point`，level=4）；
3. 输出 HugeGraph 可导入的中间 JSON；
4. 通过 Adapter 脚本写入 HugeGraph。

核心约束：**严格对齐**——只关联已存在于图谱中的四级知识点，不新建知识点节点。

---

## 2. 整体设计

### 2.1 流水线架构

```text
markdown 试卷文件
        │
        ▼
┌─────────────────────────────┐
│  Stage 1: LLM Prompt 抽取    │  输出：题目信息 + 候选知识点名称
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Stage 2: 严格匹配（代码）    │  将候选名称与已有四级知识点精确匹配
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  中间 JSON（vertices/edges/  │  Adapter 直接可消费
│  unmatched）                 │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Adapter: import_to_hg.py    │  调用 HugeGraph REST API 导入
└─────────────────────────────┘
```

### 2.2 设计原则

1. **LLM 不输出 HugeGraph 物理 id**：避免模型编造不存在的 `level_4_xxx` id。
2. **匹配逻辑由代码控制**：保证严格对齐，结果可审计。
3. **Adapter 职责单一**：只负责格式转换与 REST API 调用。
4. **未命中可追踪**：所有未匹配候选进入 `unmatched` 报告，便于人工复核。

---

## 3. Stage 1：Prompt 抽取

### 3.1 输入

```markdown
【已有四级知识点清单】
{{level_4_knowledge_points}}

【试卷 Markdown】
{{markdown_content}}
```

- `level_4_knowledge_points`：从数据库读取的 591 个四级知识点 `name` 列表，按字典序排列。
- `markdown_content`：原始试卷 markdown 文本，保留 LaTeX 公式。

### 3.2 输出 JSON Schema

```json
{
  "exam_paper": {
    "title": "string",
    "subject": "数学",
    "grade": "string",
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
      "candidate_knowledge_points": ["集合的包含关系", "子集"]
    }
  ]
}
```

### 3.3 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `exam_paper.title` | string | 是 | 试卷标题 |
| `exam_paper.subject` | string | 是 | 学科，默认"数学" |
| `exam_paper.grade` | string | 否 | 年级 |
| `exam_paper.total_score` | int | 否 | 总分 |
| `exam_paper.duration_minutes` | int | 否 | 考试时长（分钟） |
| `question_types[].name` | string | 是 | 题型名称 |
| `question_types[].description` | string | 否 | 题型描述 |
| `questions[].number` | string | 是 | 题号，如 `1`、`9`、`17(1)` |
| `questions[].content` | string | 是 | 题干原文，保留 LaTeX |
| `questions[].answer` | string | 否 | 答案，客观题尽量给出 |
| `questions[].score` | int | 否 | 分值 |
| `questions[].question_type` | string | 是 | 所属题型名称 |
| `questions[].candidate_knowledge_points` | string[] | 是 | 候选四级知识点名称 |

### 3.4 Prompt 核心约束

1. 候选知识点只列四级，不要求必须命中已有清单。
2. 题干 `content` 保留原始 LaTeX，不改写题意。
3. 题型归一化为四类：`单选题`、`多选题`、`填空题`、`解答题`。
4. 题号保持原始格式，便于定位。
5. 严格输出 JSON，不要解释文字。

---

## 4. Stage 2：严格匹配

### 4.1 匹配流程

1. 从数据库或本地缓存加载四级知识点映射：
   ```python
   level4_map = {
       "子集": "level_4_子集",
       "指数函数的性质": "level_4_指数函数的性质",
       ...
   }
   ```
2. 对每道题的 `candidate_knowledge_points` 做精确匹配。
3. 名称预处理：`strip()` 去除首尾空格，不做同义词扩展。
4. 命中的生成 `examines` 边，未命中的进入 `unmatched` 列表。

### 4.2 ID 生成策略

| 实体 | ID 格式 | 说明 |
|------|---------|------|
| `exam_paper` | `paper_{snowflake_id}` | 雪花算法生成的业务 id |
| `question` | `question_{snowflake_id}` | 雪花算法生成的业务 id，全局唯一 |
| `knowledge_point` | `level_4_{name}` | 复用已有节点 id |

`exam_paper_id` 和 `question_id` 均采用 **雪花算法** 生成，确保全局唯一且与关系库互通。

### 4.3 未命中处理

```json
{
  "unmatched": [
    {
      "question_id": "question_1148291234567890001",
      "number": "1",
      "candidate": "集合的基本运算",
      "reason": "NOT_IN_LEVEL4_LIST"
    }
  ]
}
```

---

## 5. 中间 JSON Schema

Stage 2 输出为 Adapter 的直接输入：

```json
{
  "metadata": {
    "source_file": "24-01-20高一数课堂资料（模拟卷）.md",
    "generated_at": "2026-08-01T10:00:00",
    "matching_mode": "strict"
  },
  "vertices": [
    {
      "label": "exam_paper",
      "id": "paper_1148291234567890000",
      "properties": {
        "exam_paper_id": 1148291234567890000,
        "title": "2024年高一数学期末模拟卷",
        "subject": "数学",
        "grade": "高一",
        "total_score": 150,
        "duration_minutes": 120,
        "created_at": "2026-08-01 10:00:00",
        "updated_at": "2026-08-01 10:00:00"
      }
    },
    {
      "label": "question",
      "id": "question_1148291234567890001",
      "properties": {
        "question_id": 1148291234567890001,
        "content": "已知集合 $A=\\{1,2\\}$，...",
        "answer": "A",
        "score": 5,
        "question_type_id": 1,
        "exam_paper_id": 1148291234567890000,
        "source_file_id": 2,
        "sub_file_id": 0,
        "created_at": "2026-08-01 10:00:00",
        "updated_at": "2026-08-01 10:00:00"
      }
    }
  ],
  "edges": [
    {
      "label": "contains",
      "outV": "paper_1148291234567890000",
      "inV": "question_1148291234567890001",
      "properties": {
        "create_time": "2026-08-01 10:00:00"
      }
    },
    {
      "label": "belongs_to_type",
      "outV": "question_1148291234567890001",
      "inV": "1147844797696835584",
      "properties": {
        "create_time": "2026-08-01 10:00:00"
      }
    },
    {
      "label": "examines",
      "outV": "question_1148291234567890001",
      "inV": "level_4_子集",
      "properties": {
        "create_time": "2026-08-01 10:00:00"
      }
    }
  ],
  "unmatched": [
    {
      "question_id": "question_1148291234567890001",
      "number": "1",
      "candidate": "集合的基本运算",
      "reason": "NOT_IN_LEVEL4_LIST"
    }
  ]
}
```

### 5.1 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `metadata.source_file` | string | 来源 markdown 文件名 |
| `metadata.generated_at` | string | 生成时间 ISO 8601 |
| `metadata.matching_mode` | string | 固定为 `strict` |
| `vertices` | array | 待导入顶点 |
| `vertices[].label` | string | 顶点标签 |
| `vertices[].id` | string | 物理 id（CUSTOMIZE_STRING） |
| `vertices[].properties` | object | 属性键值对 |
| `edges` | array | 待导入边 |
| `edges[].label` | string | 边标签 |
| `edges[].outV` | string | 源顶点 id |
| `edges[].inV` | string | 目标顶点 id |
| `edges[].properties` | object | 边属性 |
| `unmatched` | array | 未匹配候选知识点列表 |

---

## 6. Adapter 脚本设计

### 6.1 脚本职责

`import_to_hg.py` 负责：

1. 读取 Stage 2 生成的中间 JSON。
2. 校验必填字段。
3. 按依赖顺序导入：
   - `exam_paper` 顶点
   - `question` 顶点
   - `contains` 边
   - `belongs_to_type` 边（通过题型 `name` 查询已有 `question_type` 顶点物理 id）
   - `examines` 边
4. 调用 HugeGraph REST API。
5. 记录导入结果与失败项。
6. 输出 `unmatched` 报告。

### 6.2 REST API 调用格式

与现有 `graph_service.py` 保持一致：

```python
# 创建顶点
POST /graphspaces/DEFAULT/graphs/edu/graph/vertices
{
  "label": "question",
  "id": "question_2_1",
  "type": "vertex",
  "properties": {
    "question_id": 201,
    "content": "...",
    ...
  }
}

# 创建边
POST /graphspaces/DEFAULT/graphs/edu/graph/edges
{
  "label": "examines",
  "outV": "question_2_1",
  "inV": "level_4_子集",
  "properties": {
    "create_time": "2026-08-01 10:00:00"
  }
}
```

### 6.3 幂等性

- `exam_paper` 和 `question` 使用 `CUSTOMIZE_STRING` id，重复导入同一 id 时 HugeGraph 会返回错误。
- Adapter 应捕获 400/409 状态码，记录为 `duplicated`，默认跳过。
- 该行为可通过配置开关控制：跳过或报错终止。

### 6.4 输出报告

```json
{
  "import_summary": {
    "vertices_total": 23,
    "vertices_created": 21,
    "vertices_duplicated": 2,
    "edges_total": 45,
    "edges_created": 43,
    "edges_failed": 2
  },
  "unmatched_count": 5,
  "unmatched_file": "unmatched_2026-08-01.json"
}
```

---

## 7. 错误处理

| 问题 | 处理策略 |
|------|---------|
| LLM 输出非 JSON 或结构缺失 | 捕获异常，重试 3 次，仍失败则写入 `error_log.json` |
| 候选知识点未命中四级清单 | 进入 `unmatched`，不生成 `examines` 边 |
| 题号冲突 | 使用雪花算法生成 `question_id`，物理 id 为 `question_{snowflake_id}`，全局唯一 |
| 题型顶点不存在 | 当前数据库已补齐四类题型；如仍缺失则报错并跳过该题 |
| HugeGraph 顶点已存在 | 记录为 `duplicated`，默认**跳过**，保持幂等性 |
| 边创建失败（顶点缺失） | 记录失败边，支持按依赖顺序断点重试 |

---

## 8. 验收标准

1. 给定一个 markdown 试卷文件，能成功输出符合中间 JSON Schema 的文件。
2. 所有 `examines` 边的 `inV` 必须是数据库中已存在的 `level_4_xxx` id。
3. `unmatched` 列表完整，候选名称、题号、原因齐全。
4. Adapter 能将中间 JSON 成功导入 HugeGraph，并返回导入报告。
5. 重复导入同一试卷时，不破坏已有数据，记录重复项。

---

## 9. 不在本次范围内

- 不新增四级知识点节点。
- 不做题型/解法/公式定理/易错点的深度抽取（本次仅做题目 + 四级知识点关联）。
- 不做语义匹配或别名扩展（未来可在 Stage 2 中扩展，不影响主流程）。
- 不修改现有 `education_kg_schema.groovy` 定义的 Schema。

---

## 10. 已确认事项

1. ✅ `exam_paper_id` 和 `question_id` 均采用 **雪花算法** 生成；物理 id 分别为 `paper_{snowflake_id}` 和 `question_{snowflake_id}`。
2. ✅ 当 `question` 顶点已存在（id 冲突）时，Adapter 默认**跳过**，保持幂等性。
3. ✅ 数据库已补齐四类题型顶点：
   - `单选题`：id=`1147844797696835584`，question_type_id=`1`
   - `多选题`：id=`1148295326331830272`，question_type_id=`2`
   - `填空题`：id=`1147844798275649536`，question_type_id=`3`
   - `解答题`：id=`1148295342110801920`，question_type_id=`4`
   
   Adapter 通过题型 `name` 查询已有顶点获取物理 id。

---

## 11. 实现文件索引

- `exam_extract/models.py`：Pydantic 模型
- `exam_extract/prompt.py`：Prompt 构建与知识点加载
- `exam_extract/matcher.py`：Stage 2 严格匹配
- `exam_extract/adapter.py`：Stage 3 HugeGraph 导入
- `exam_extract/cli.py`：命令行入口
- `prompts/exam_extract.md`：LLM Prompt 模板
