# 教育场景知识图谱 Schema 说明

> 基于 [education_kg_schema.groovy](file:///Users/edy/PycharmProjects/jysj/graph/education_kg_schema.groovy)（HugeGraph graph + graph-groovy 语法），结合《教育场景知识构建模块》知识抽取模块及《高中数学知识点-包含与相关.xlsx》《24-01-20高一数课堂资料（模拟卷）.md》设计。
>
> 调整记录：
> - 去除除知识点和题目外其余实体的 `source_file_id` 属性；去除题目的 `difficulty_level` 属性
> - 明确试卷→题目的 `contains` 包含关系
> - **知识点 / 题目 / 试卷改为自定义 id（CUSTOMIZE_STRING 策略）**
>   - knowledge_point 物理 id 格式：`level_{L}_{name}`，同一 name 不同 level 视为不同顶点（独立存储、独立检索）
>   - question 物理 id：`question_{N}`；exam_paper 物理 id：`paper_{N}`
> - 知识点新增 `level`（等级）属性，按 xlsx 中一级/二级/三级/四级自动赋值 1/2/3/4，仅出现在相关关系中的设为 0
> - **四级知识点为空时，沿用三级名作为独立的第 4 级顶点**（避免缺失叶子节点）

## 一、整体概览

| 类别 | 数量 | 说明 |
|------|------|------|
| 顶点标签 | 7 | 知识点、题型、解法、公式定理、易错点、试卷、题目（核心） |
| 边标签 | 9 | 题目出 6 条 + 试卷 1 条 + 知识点间 2 条 |
| 属性键 | 28 | 通用 + 实体业务主键 + 边属性（已去除 `difficulty_level`） |
| 索引 | 8 | 7 个 SECONDARY 名称/学科/等级/来源 + 1 个边排序（新增 knowledge_point_level） |

### 实际数据规模（截至 2026-07-31）

| 顶点 | 数量 | 边 | 数量 |
|------|------|----|------|
| knowledge_point | 970（含 6 个真实独立 level_0） | contains_kp | 975 |
| question | 22 | related_kp | 104 |
| exam_paper | 1 | examines | 76 |
| question_type | 4 | contains | 22 |
| solution | 22 | belongs_to_type | 22 |
| formula_theorem | 20 | solved_by | 22 |
| error_prone | 22 | uses_formula | 20 |
| | | prone_to_error | 22 |

**知识点层级分布**：level_1=13、level_2=80、level_3=280、level_4=591、level_0=6（仅出现在相关关系中的独立节点）。

**同名不同级节点**：170 组（如「数学归纳法」同时存在于 level 2/3/4），均作为独立顶点存储，物理 id 格式为 `level_{L}_{name}`。

## 二、顶点（实体）

### 1. knowledge_point — 知识点

**id 策略：CUSTOMIZE_STRING**（创建时显式提供 `id` 字符串）

**物理 id 格式：`level_{L}_{name}`**，其中 L ∈ {0,1,2,3,4} 为等级，`name` 为中文知识点名。

**同一 name 不同 level 视为不同顶点**（独立存储、独立检索）。例如 `集合的概念` 在 xlsx 中既出现在三级又出现在四级，会同时产生 `level_3_集合的概念` 和 `level_4_集合的概念` 两个顶点。

教育知识体系的核心节点。

| 属性 | 类型 | 可空 | 说明 |
|------|------|------|------|
| knowledge_point_id | LONG | 否 | 业务主键，全局唯一（自增分配，与物理 id 解耦） |
| name | TEXT | 否 | 知识点名称（如"交集""指数函数性质"） |
| description | TEXT | 是 | 知识点描述 |
| subject | TEXT | 是 | 所属学科（默认"数学"） |
| **level** | **INT** | **是** | **知识点层级：1=一级/2=二级/3=三级/4=四级/0=仅出现在相关关系中未分级** |
| source_file_id | LONG | 是 | 来源文件 id（默认 0 表示默认来源） |
| created_at | TEXT | 是 | 创建时间 |
| updated_at | TEXT | 是 | 更新时间 |

**索引**：`name` SECONDARY、`subject` SECONDARY、`level` SECONDARY

### 2. question_type — 题型

| 属性 | 类型 | 可空 | 说明 |
|------|------|------|------|
| question_type_id | LONG | 否 | 业务主键 |
| name | TEXT | 否 | 题型名（单选/多选/填空/解答题） |
| description | TEXT | 是 | 题型描述 |
| created_at / updated_at | TEXT | 是 | 时间戳 |

> **已去除** `source_file_id`

**索引**：`question_type_id` UNIQUE、`name` SECONDARY

### 3. solution — 解法

| 属性 | 类型 | 可空 | 说明 |
|------|------|------|------|
| solution_id | LONG | 否 | 业务主键 |
| title | TEXT | 否 | 解法名称 |
| content | TEXT | 否 | 解题思路详细内容 |
| created_at / updated_at | TEXT | 是 | 时间戳 |

> **已去除** `source_file_id`、`difficulty_level`

**索引**：`solution_id` UNIQUE、`title` SECONDARY

### 4. formula_theorem — 公式定理

| 属性 | 类型 | 可空 | 说明 |
|------|------|------|------|
| formula_theorem_id | LONG | 否 | 业务主键 |
| name | TEXT | 否 | 公式/定理名 |
| expression | TEXT | 否 | 表达式（LaTeX） |
| description | TEXT | 是 | 说明 |
| formula_type | INT | 否 | 类型：0-公式 / 1-定理 |
| created_at / updated_at | TEXT | 是 | 时间戳 |

> **已去除** `source_file_id`

**索引**：`formula_theorem_id` UNIQUE、`name` SECONDARY

### 5. error_prone — 易错点

| 属性 | 类型 | 可空 | 说明 |
|------|------|------|------|
| error_prone_id | LONG | 否 | 业务主键 |
| title | TEXT | 否 | 易错点标题 |
| description | TEXT | 否 | 详细描述 |
| cause_analysis | TEXT | 是 | 错误原因分析 |
| created_at / updated_at | TEXT | 是 | 时间戳 |

> **已去除** `source_file_id`

**索引**：`error_prone_id` UNIQUE、`title` SECONDARY

### 6. exam_paper — 试卷

**id 策略：CUSTOMIZE_STRING**（创建时显式提供 `id` 字符串，物理 id = 业务 id 字符串形式）

| 属性 | 类型 | 可空 | 说明 |
|------|------|------|------|
| exam_paper_id | LONG | 否 | 业务主键 |
| title | TEXT | 否 | 试卷标题 |
| subject | TEXT | 是 | 学科 |
| grade | TEXT | 是 | 年级 |
| total_score | INT | 是 | 总分 |
| duration_minutes | INT | 是 | 考试时长（分钟） |
| created_at / updated_at | TEXT | 是 | 时间戳 |

> **已去除** `source_file_id`

**索引**：`exam_paper_id` UNIQUE、`title` SECONDARY

### 7. question — 题目（核心实体）

**id 策略：CUSTOMIZE_STRING**（创建时显式提供 `id` 字符串）

| 属性 | 类型 | 可空 | 说明 |
|------|------|------|------|
| question_id | LONG | 否 | 业务主键 |
| content | TEXT | 否 | 题干内容（含 LaTeX） |
| answer | TEXT | 是 | 答案 |
| score | INT | 是 | 分值 |
| question_type_id | LONG | 是 | 冗余存题型 id |
| exam_paper_id | LONG | 是 | 冗余存试卷 id |
| source_file_id | LONG | 是 | **来源文件 id**（保留） |
| sub_file_id | LONG | 是 | 来源子文件 id |
| created_at / updated_at | TEXT | 是 | 时间戳 |

> **已去除** `difficulty_level`

**索引**：`question_id` UNIQUE、`source_file_id` SECONDARY

## 三、边（关系）

| 边标签 | 中文 | 起点 → 终点 | 频率 | 边属性 | 说明 |
|--------|------|------------|------|--------|------|
| **examines** | 考查 | question → knowledge_point | SINGLE | create_time | 一题考查哪些知识点 |
| **belongs_to_type** | 属于 | question → question_type | SINGLE | create_time | 题目所属题型 |
| **solved_by** | 可由求解 | question → solution | MULTIPLE | sequence, create_time | 一题多解法，`sequence` 排序 |
| **uses_formula** | 使用 | question → formula_theorem | SINGLE | create_time | 题目用到的公式定理 |
| **prone_to_error** | 易犯 | question → error_prone | SINGLE | create_time | 题目关联的易错点 |
| **variant_of** | 关联变式 | question → question | SINGLE | relation_desc, create_time | 原题 ↔ 变式题 |
| **contains** | **包含** | **exam_paper → question** | SINGLE | create_time | **试卷包含题目** |
| **contains_kp** | 包含 | knowledge_point → knowledge_point | SINGLE | create_time | 知识点层级（一级→二级→三级→四级） |
| **related_kp** | 相关 | knowledge_point → knowledge_point | SINGLE | create_time | 知识点间关联 |

**说明**：
- `SINGLE`/`MULTIPLE` 为 HugeGraph 边频率。`solved_by` 用 `MULTIPLE` + `sortKeys('sequence')` 支持多解法按序区分。
- 所有边均带 `create_time`（可空）。

## 四、关系拓扑图

```
                        ┌──────────────┐
                        │  exam_paper  │ 试卷
                        └──────┬───────┘
                               │ contains 包含
                               ▼
   question_type ◄──belongs_to_type──┌──────────┐──examines──►  knowledge_point
     题型             属于              │ question │   考查             │   ▲
                                       │  题目    │             contains_kp│   │related_kp
   solution   ◄────solved_by─────────  │ (核心)   │             包含(层级) │   │相关
     解法          可由求解            └──┬───┬───┘                        ▼   │
                                          │   │                     knowledge_point
   formula_theorem ◄──uses_formula────────┘   │
     公式定理          使用                     │ prone_to_error 易犯
                                               ▼
                                          error_prone 易错点

   question ──variant_of──► question   （原题 关联 变式题）
```

## 五、设计要点

1. **question 是枢纽**：6 类边以 question 为起点，构成以题目为中心的星型结构。
2. **知识点自成网络**：通过 `contains_kp`（层级）与 `related_kp`（横向）建立知识图，支撑学习路径推荐、相关知识点挖掘。
3. **业务主键 + 唯一索引**：每类实体都有 `*_id` 唯一索引，与 MySQL 关系库互通追溯。
4. **id 策略**（全部走 CUSTOMIZE_STRING，调用时显式提供 id 字符串）：
   - 知识点：**`kp_<knowledge_point_id>`**，如 `kp_1` → 集合与逻辑
   - 试卷：**`paper_<exam_paper_id>`**，如 `paper_1`
   - 题目：**`question_<question_id>`**，如 `question_1` … `question_22`
   - 其余 4 类（题型/解法/公式定理/易错点）仍为 **AUTOMATIC**（自动雪花 id）
   - HugeGraph v4 枚举为 `IdStrategy.CUSTOMIZE_STRING`，groovy 客户端使用 `useCustomizeId()`，无 `primary_keys`
5. **来源追溯**：`source_file_id` 仅保留在 **knowledge_point** 与 **question** 两类实体上（题目额外带 `sub_file_id` 关联子文件）。
6. **难度简化**：`difficulty_level` 已去除，不在题目/解法上保留难度字段。如需难度分析，可通过 `score`、`subject` 等其他字段或独立的标签实体承载。
7. **知识点层级**：`knowledge_point.level` 字段记录 1-4 级（0=仅出现在相关关系中），同名节点取最大级；`subject` 默认"数学"、`source_file_id` 默认 0。`knowledge_point_level` 二级索引支持按层级快速筛选。


