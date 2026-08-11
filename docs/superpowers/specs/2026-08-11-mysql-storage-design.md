# MySQL 存储表结构 & 独立导入 API 设计

> 状态：已确认 | 日期：2026-08-11

## 背景

为高中数学题库系统新增 MySQL 关系存储，承载**学生作答得分**和**薄弱知识点推荐**等业务场景。与现有 HugeGraph（图库）和 Milvus（向量库）配合使用，通过统一的 ID 派生逻辑桥接三套存储，但 API 和入库流程完全独立，不耦合。

## 核心决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 数据库 | MySQL | 关系型，JOIN/聚合方便 |
| 试题/试卷主键 | VARCHAR(64)，沿用 `paper_{md5}` / `question_{md5}` | 与 HugeGraph/Milvus ID 一致，零翻译成本 |
| 知识点表 | INT 自增 + parent_id 树形 | 几百条数据，不需要物化路径 |
| 同类题 | 不单独建表 | SQL 按知识点+题型+难度过滤即可 |
| 判分 | 不做 | 教师已在答题卡上判好分数，系统只收集 |
| 与现有流水线关系 | 完全独立 | 复用 ID 生成逻辑，不复用入库流程 |

## 表结构

### 1. `exam_papers` 试卷

```sql
CREATE TABLE exam_papers (
    id          VARCHAR(64)  PRIMARY KEY,          -- paper_{md5hex}，MD5(source_file)
    title       VARCHAR(200) NOT NULL,             -- 试卷标题
    grade       VARCHAR(20),                       -- 年级，如"高一""高二""高三"
    subject     VARCHAR(20)  DEFAULT '数学',
    total_score INT,                               -- 试卷总分
    duration_minutes INT,                          -- 考试时长（分钟）
    exam_type   VARCHAR(20),                       -- 月考/期中/期末/模拟/高考
    paper_year  INT,                               -- 年份
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### 2. `questions` 题目

```sql
CREATE TABLE questions (
    id                  VARCHAR(64)  PRIMARY KEY,  -- question_{md5hex}，MD5(source_file:题号)
    exam_paper_id       VARCHAR(64)  NOT NULL,     -- FK → exam_papers
    number              VARCHAR(20)  NOT NULL,     -- 题号
    content             TEXT         NOT NULL,     -- 题目正文（Markdown + LaTeX）
    answer              TEXT,                      -- 标准答案（Markdown + LaTeX）
    score               INT,                       -- 分值
    question_type       VARCHAR(20)  NOT NULL,     -- 单选题/多选题/填空题/解答题
    difficulty          TINYINT,                   -- 难度 1-5
    knowledge_point_ids JSON,                      -- 关联四级知识点 ID，如 [12, 45, 78]
    img_url             JSON,                      -- 题目图片 URL 列表
    answer_img          JSON,                      -- 答案图片 URL 列表
    sort_order          INT,                       -- 试卷内排序
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (exam_paper_id) REFERENCES exam_papers(id)
);
```

> `knowledge_point_ids` 用 JSON 存，一道题关联多个四级知识点。查询用 `JSON_CONTAINS`。

### 3. `knowledge_points` 四级知识点

```sql
CREATE TABLE knowledge_points (
    id        INT          AUTO_INCREMENT PRIMARY KEY,
    name      VARCHAR(100) NOT NULL,
    level     TINYINT      NOT NULL,               -- 1/2/3/4
    parent_id INT          NULL,                   -- 上级知识点，一级为 NULL
    sort_order INT         DEFAULT 0,

    FOREIGN KEY (parent_id) REFERENCES knowledge_points(id)
);
```

### 4. `formulas_theorems` 公式定理

```sql
CREATE TABLE formulas_theorems (
    id                  INT          AUTO_INCREMENT PRIMARY KEY,
    name                VARCHAR(200) NOT NULL,
    content             TEXT         NOT NULL,      -- LaTeX 公式
    description         TEXT,                       -- 文字说明、适用条件
    knowledge_point_id  INT          NOT NULL,      -- 关联四级知识点
    created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id)
);
```

### 5. `students` 学生

```sql
CREATE TABLE students (
    id         INT          AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(50)  NOT NULL,
    grade      VARCHAR(20),                        -- 年级
    class_name VARCHAR(30),                        -- 班级
    school_name VARCHAR(100),                      -- 学校名称（避免多表 JOIN，直接存）
    student_no VARCHAR(30),                        -- 学号
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_school_no (school_name, student_no)
);
```

### 6. `answer_sheets` 答题卡（学生作答）

```sql
CREATE TABLE answer_sheets (
    id              INT          AUTO_INCREMENT PRIMARY KEY,
    student_id      INT          NOT NULL,          -- FK → students
    exam_paper_id   VARCHAR(64)  NOT NULL,          -- FK → exam_papers
    question_id     VARCHAR(64)  NOT NULL,          -- FK → questions
    student_answer  TEXT,                           -- 学生作答内容（OCR 识别）
    score_obtained  DECIMAL(5,1),                   -- 教师判分（从答题卡提取）
    is_correct      TINYINT,                        -- 0错/1对/NULL未析
    answer_img      JSON,                           -- 学生答题卡图片 URL
    marked_at       DATETIME,                       -- 判分时间（答题卡上的日期）
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (student_id)    REFERENCES students(id),
    FOREIGN KEY (exam_paper_id) REFERENCES exam_papers(id),
    FOREIGN KEY (question_id)   REFERENCES questions(id),
    UNIQUE KEY uk_student_q (student_id, question_id, exam_paper_id)
);
```

> `score_obtained` / `is_correct` 从答题卡 OCR 结果中提取，教师已在纸上判好分。

---

## ID 桥接机制

三套存储共享同一套 ID，通过 `hashlib.md5()` 确定性派生：

```
paper_id    = f"paper_{MD5(source_file)}"
question_id = f"question_{MD5(f'{source_file}:{q.number}')}"
```

| 存储 | 用途 | ID 格式 |
|---|---|---|
| HugeGraph | 知识点图、试卷-题目-知识点关系 | `paper_{md5}` / `question_{md5}` |
| Milvus | 题目向量（dense + BM25 稀疏） | `question_id: VARCHAR` |
| MySQL | 试卷/题目/学生/作答/公式定理 | `paper_{md5}` / `question_{md5}`（VARCHAR PK） |

**优点**：跨系统 JOIN 无需 ID 翻译，一条 `question_id` 在三个系统间自由穿梭。

---

## API 设计

所有文件已预存在 MinIO 中，API 只接受 `object_key` 去读取。

### `POST /api/v1/mysql/import/paper`

从 MinIO 读取试卷 Markdown，LLM 抽取后写库。

```json
// Request
{
    "object_key": "papers/2024-gaokao-math.md"
}

// Response
{
    "paper_id": "paper_f3ab19e8...",
    "title": "2024年高考数学全国卷I",
    "question_count": 22,
    "imported": true
}
```

**流程**：MinIO 取文件 → LLM 抽取（复用 prompt + llm 服务，不连 HugeGraph/Milvus）→ 写 `exam_papers` + `questions`

### `POST /api/v1/mysql/import/answers`

从 MinIO 读取标准答案 Markdown，解析后更新已有题目。

```json
// Request
{
    "object_key": "answers/2024-gaokao-answers.md",
    "paper_id": "paper_f3ab19e8..."
}

// Response
{
    "paper_id": "paper_f3ab19e8...",
    "updated_count": 22
}
```

### `POST /api/v1/mysql/import/answer-sheet`

从 MinIO 读取答题卡图片，OCR 识别学生信息和各题得分后写库。

```json
// Request
{
    "object_key": "answer-sheets/zhangsan-gaokao.jpg",
    "paper_id": "paper_f3ab19e8..."
}

// Response
{
    "student_id": 42,
    "student_name": "张三",
    "paper_id": "paper_f3ab19e8...",
    "scored_count": 22,
    "total_obtained": 128
}
```

**流程**：MinIO 取图片 → OCR → 提取学生信息（姓名/班级/学号）→ 提取各题得分 → UPSERT `students` → 写 `answer_sheets`

### `GET /api/v1/mysql/export/csv`

导出指定表为 CSV。后续切换为只输出 CSV 不入库。

```json
// Request
{
    "tables": ["exam_papers", "questions", "answer_sheets"],
    "paper_id": "paper_f3ab19e8..."   // 可选，按试卷过滤
}

// Response: application/zip
// ├── exam_papers.csv
// ├── questions.csv
// └── answer_sheets.csv
```

---

## 核心查询：薄弱知识点推荐

```sql
-- 找到某学生某次试卷的薄弱知识点（正确率 < 60%）
SELECT kp.id, kp.name,
       COUNT(*) AS total,
       SUM(a.is_correct) AS correct,
       ROUND(SUM(a.is_correct) / COUNT(*), 2) AS accuracy
FROM answer_sheets a
JOIN questions q ON a.question_id = q.id
JOIN JSON_TABLE(q.knowledge_point_ids, '$[*]' COLUMNS (kp_id INT PATH '$')) jt
JOIN knowledge_points kp ON kp.id = jt.kp_id
WHERE a.student_id = ?
  AND a.exam_paper_id = ?
  AND a.is_correct IS NOT NULL
GROUP BY kp.id, kp.name
HAVING accuracy < 0.6;

-- 推荐同类题（同四级知识点 + 同题型 + 相近难度，且学生未做过）
SELECT q.*
FROM questions q
WHERE JSON_CONTAINS(q.knowledge_point_ids, '?')
  AND q.question_type = ?
  AND q.difficulty BETWEEN ?-1 AND ?+1
  AND q.id NOT IN (
      SELECT question_id FROM answer_sheets WHERE student_id = ?
  )
ORDER BY q.difficulty
LIMIT 10;
```

---

## 与现有系统的边界

```
现有流水线（不动）：
  试卷 MD → LLM 抽取 → HugeGraph + Milvus   ← 幂等导入，知识图谱 + 语义搜索

新增 API（独立）：
  试卷 MD (MinIO) → LLM 抽取 → MySQL         ← 独立入库通道
  答案 MD (MinIO) → 解析    → MySQL
  答题卡图 (MinIO) → OCR   → MySQL

共享：
  - hashlib.md5() ID 派生逻辑
  - LLM Prompt 构建（service/prompt.py）
  - MinIO 读取（libs/minio.py）
```

---

## 后续扩展

- **入库/CSV 切换**：请求加 `mode` 参数（`mysql` | `csv`），CSV 模式跳过入库直接返回文件
- **Milvus 向量补充**：推荐时加入向量相似度排序，同类题不仅靠规则过滤，还靠语义相似度打分
- **同类题表**：如果规则过滤不满足需求，再加 `similar_questions` 表，由教师标注维度标签
