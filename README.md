# 试卷抽取与知识点关联导入工具

从高中数学 Markdown 试卷中抽取试卷、题目、题型信息，自动关联到 HugeGraph 知识图谱中**已有**的四级知识点，同时将题目和知识点的向量写入 Milvus，支持语义搜索。

## 核心能力

- **Markdown 试卷解析**：从 MinIO 读取试卷 Markdown，保留 LaTeX 公式。
- **LLM 自动抽取**：支持 OpenAI-compatible API（OpenAI、DeepSeek、Qwen 等），自动抽取题目与候选四级知识点。
- **严格知识点对齐**：将 LLM 给出的候选知识点名称与 HugeGraph 中已有的四级知识点精确匹配，未命中项进入 `unmatched` 报告，不新建知识点。
- **多策略匹配兜底**：精确匹配失败时，自动回退到 embedding 语义匹配（需配置 Embedding 服务），提升知识点召回率。
- **向量双写**：抽取过程中将题目和知识点同步写入 Milvus 向量库（dense + BM25 稀疏向量），供语义检索使用。
- **混合语义搜索**：支持 Dense + BM25 混合检索试题，可按知识点层级进行标量过滤。
- **幂等导入**：试卷和题目的顶点 ID 由源文件路径确定性派生（MD5），重复导入同一份试卷时 HugeGraph 自动跳过已存在顶点和边，不会产生重复数据。
- **中间产物审计**：支持将 LLM 原始输出和匹配后的中间 JSON 落盘，人工复核 `unmatched` 清单后再导入。
- **Redis Stream 异步消费**：支持通过 MinIO webhook → Redis Stream 事件驱动异步抽取。
- **雪花 ID**：CLI 工具保留雪花 ID 生成器，供其他工具链使用。

## 项目结构

```text
.
├── main.py                     # FastAPI 应用入口
├── cli.py                      # 命令行入口
├── Dockerfile                  # Docker 镜像构建
├── docker-compose.yml          # 本地开发环境（含 Milvus/Redis/MinIO）
├── docker-compose.prod.yml     # 生产部署 Compose
├── bin/                        # 启动/部署脚本
│   ├── deploy.sh               # 一键部署脚本
│   └── backfill_milvus.py      # Milvus 历史数据回填
├── conf/                       # 配置
│   └── config.py               # pydantic-settings 配置中心
├── core/                       # 基础机制
│   ├── exceptions.py           # 统一异常定义
│   └── events.py               # Redis Streams 生产者/消费者
├── libs/                       # 外部系统封装
│   ├── hugegraph.py            # HugeGraph REST API 封装
│   ├── milvus.py               # Milvus 异步 SDK 封装（dense + BM25）
│   ├── minio.py                # MinIO 异步 SDK 封装
│   └── embed_client.py         # BGEM3 Embedding HTTP 客户端
├── model/                      # 纯 Pydantic 数据模型
│   ├── models.py               # 领域模型
│   └── schemas.py              # API 请求/响应 DTO
├── service/                    # 业务逻辑
│   ├── api/                    # HTTP 接口层
│   │   ├── deps.py             # FastAPI 依赖注入
│   │   ├── router.py           # 路由汇总
│   │   └── endpoints/          # 端点处理函数
│   ├── extraction.py           # 抽取流水线编排
│   ├── knowledge.py            # 知识点/试卷查询
│   ├── llm.py                  # AsyncOpenAI LLM 调用
│   ├── matcher.py              # 知识点匹配（精确 + embedding 兜底）
│   ├── embedding.py            # Embedding 向量化服务
│   ├── search.py               # Milvus 混合语义搜索
│   ├── minio.py                # MinIO 文件浏览服务
│   ├── prompt.py               # Prompt 构建
│   └── scoring/                # OCR markdown 解析（判分）
├── utils/                      # 通用工具
│   ├── snowflake.py            # 简易雪花 ID 生成器
│   └── paths.py                # 项目路径管理
├── logs/                       # 日志配置
│   └── logging.py
├── prompts/                    # LLM Prompt 模板
├── scripts/                    # 辅助脚本
│   └── md_to_docx.py           # Markdown 转 DOCX
├── tests/                      # 测试集
│   ├── unit/                   # 单元测试
│   ├── integration/            # 集成测试
│   └── fixtures/               # 测试固件
├── reference/                  # 参考资料
├── docs/                       # 文档
├── deploy.md                   # 部署说明
├── requirements.txt
└── README.md
```

## 安装

### 本地开发

```bash
pip install -r requirements.txt
```

### Docker 开发环境

一键启动所有依赖服务（Milvus + Redis + MinIO）和 API：

```bash
docker compose up -d          # 启动全部服务
docker compose up -d api      # 仅启动 API + 依赖
docker compose logs -f        # 查看日志
docker compose down           # 停止
```

API 服务默认监听 `http://localhost:8000`（映射容器内 8085）。

## 配置

在项目根目录创建 `.env`（参考 `.env.example`）：

```env
# LLM
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
LLM_MAX_TOKENS=16384
LLM_TEMPERATURE=0.0
LLM_TIMEOUT=120.0

# MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=exams
MINIO_SECURE=false

# Redis
REDIS_URL=redis://localhost:6379/0

# HugeGraph
HG_HOST=202.107.249.39
HG_PORT=50045
HG_USER=admin
HG_PASSWD=admin
HG_GRAPHSPACE=DEFAULT
HG_GRAPH=edu

# Milvus（向量库）
MILVUS_URI=http://localhost:19530
MILVUS_DB=default
MILVUS_QUESTION_COLLECTION=question_embed_v1
MILVUS_KP_COLLECTION=kp_embed_v1

# Embedding（BGEM3 向量化服务，可选）
EMBED_BASE_URL=http://<embedding-server-ip>:8026
EMBED_ENDPOINT=/api/bgem3/encoder
EMBED_LOAD_SERVICE=llm_search
EMBED_DIM=1024
EMBED_TIMEOUT=60.0
EMBED_KP_MATCH_THRESHOLD=0.75
EMBED_KP_TOP_K=5

# App
DEBUG=false
OUTPUT_DIR=tmp/extractions
```

所有配置项支持环境变量覆盖，详见 `conf/config.py`。

> **注意**：Embedding 服务为可选组件。未配置时，知识点匹配仅使用精确匹配；向量搜索 API 将返回 503。

## 快速开始

### 方式一：Web API

启动服务：

```bash
# 本地开发（端口 8080）
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# Docker 开发环境（映射到宿主机 8000）
docker compose up -d
```

**审计模式（推荐）：先抽取落盘，人工复核后再导入**

```bash
# 第 1 步：仅抽取 + 保存产物，不入库
curl -X POST http://localhost:8080/api/edu/extract \
  -H 'Content-Type: application/json' \
  -d '{"object_key":"education/uploads/.../模拟卷.md",
       "save_artifacts":true, "import_to_hg":false}'

# 返回：
# {"paper_id":"paper_890e5428fd13...",
#  "question_count":30, "matched_kp":68, "unmatched_count":21,
#  "artifact_dir":"tmp/extractions/890e5428fd13", "imported":false}
```

审计产物：

```bash
ls tmp/extractions/890e5428fd13/
# llm_response.json      # LLM 原始输出（试题+答案+候选知识点）
# intermediate.json      # 匹配后中间 JSON（vertices/edges/unmatched）

# 重点审计 unmatched 清单
cat tmp/extractions/890e5428fd13/intermediate.json \
  | python -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d['unmatched'], indent=2, ensure_ascii=False))"
```

**第 2 步：审计通过后导入**

```bash
curl -X POST http://localhost:8080/api/edu/extract \
  -H 'Content-Type: application/json' \
  -d '{"object_key":"education/uploads/.../模拟卷.md",
       "save_artifacts":false, "import_to_hg":true}'
```

> 第二次运行 paper_id 相同，HugeGraph 侧幂等跳过已存在的顶点和边。

**直接导入模式（跳过审计）**

```bash
# 默认行为：save_artifacts=false, import_to_hg=true
curl -X POST http://localhost:8080/api/edu/extract \
  -H 'Content-Type: application/json' \
  -d '{"object_key":"education/uploads/.../模拟卷.md"}'
```

### 方式二：CLI

```bash
# 审计模式：仅抽取，不入库
python cli.py \
  --object-key "education/uploads/.../模拟卷.md" \
  --save-artifacts --skip-import

# 直接导入模式
python cli.py \
  --object-key "education/uploads/.../模拟卷.md" \
  --save-artifacts
```

## API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/edu/extract` | 试卷抽取（支持审计/导入模式） |
| `GET` | `/api/edu/minio/files` | MinIO `.md` 文件列表 |
| `POST` | `/api/edu/minio/webhook/minio` | MinIO bucket 事件回调 |
| `GET` | `/api/edu/knowledge` | 四级知识点列表 |
| `GET` | `/api/edu/knowledge/{kp_id}` | 单个知识点详情 |
| `GET` | `/api/edu/papers` | 已导入试卷列表 |
| `GET` | `/api/edu/papers/{paper_id}` | 试卷详情 |
| `GET` | `/api/edu/papers/{paper_id}/questions` | 试卷题目列表 |
| `GET` | `/api/edu/questions/{question_id}` | 题目详情 |
| `POST` | `/api/edu/scoring/parse` | OCR markdown 解析为判分 JSON（不走 LLM） |
| `POST` | `/api/edu/search/questions` | 试题语义搜索（dense + BM25 混合检索） |

### 抽取请求参数

```json
{
  "object_key": "education/uploads/.../模拟卷.md",
  "save_artifacts": false,
  "import_to_hg": true
}
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `object_key` | string | 必填 | MinIO 文件路径 |
| `save_artifacts` | bool | `false` | 是否将 LLM 输出和中间 JSON 落盘到 `tmp/extractions/` |
| `import_to_hg` | bool | `true` | 是否导入 HugeGraph |

## OCR Markdown 解析（判分）

```
POST /api/edu/scoring/parse
```

上传 PDF 试卷文件，调用 OCR 服务解析后返回结构化判分数据。纯规则解析不走 LLM。用于提取学生作答与标准答案，供后续判分流程使用。

**Content-Type**: `multipart/form-data`

**请求**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | PDF 试卷文件 |
| `paper_id` | string | 否 | 试卷 ID。传入时为**答题卡模式**（查 HugeGraph 补全），不传为**完整试卷模式**（纯 OCR 解析） |

**示例**：

```bash
# 答题卡模式
curl -X POST "http://localhost:8080/api/edu/scoring/parse" \
  -F "file=@/path/to/answer_sheet.pdf" \
  -F "paper_id=paper_xxx"

# 完整试卷模式
curl -X POST "http://localhost:8080/api/edu/scoring/parse" \
  -F "file=@/path/to/exam_paper.pdf"
```

**响应**：

```json
{
  "paper_title": "华岳高级中学 2026 年上学期入学考试",
  "paper_id": "paper_dc4dd20716edca6077883ecddea78242",
  "total_score": 100,
  "questions": [
    {
      "number": "1",
      "question_id": "question_6b15094904b0f2f5db11b34efff2deab",
      "content": "若集合 $A=\\{x\\mid 3^x>9\\}$ ...",
      "student_answer": null,
      "standard_answer": "C",
      "score": 4,
      "question_type": "单选题",
      "exam_paper_id": "992160949340134566",
      "exam_paper_title": "华岳高级中学 2026 年上学期入学考试",
      "knowledge_points": ["并集", "指数函数图象", "一元二次不等式"],
      "img_url": [],
      "answer_img": [],
      "student_img": []
    }
  ],
  "ocr_markdown": "..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `number` | string | 题号 |
| `question_id` | string | 试题 ID |
| `content` | string | 题目内容（含 LaTeX、HTML 图片标签） |
| `student_answer` | string\|null | 学生作答（从答题卡表格提取） |
| `standard_answer` | string\|null | 标准答案（答题卡模式查 HugeGraph，完整试卷模式从参考答案区域提取） |
| `score` | int\|null | 本题分值 |
| `question_type` | string | 题型：单选题/多选题/填空题/解答题 |
| `exam_paper_id` | string | 所属试卷 ID |
| `exam_paper_title` | string | 所属试卷标题 |
| `knowledge_points` | string[] | 关联知识点（答题卡模式已填充，完整试卷模式为空） |
| `img_url` | string[] | 试题图片 URL（数据库存储） |
| `answer_img` | string[] | 答案图片 URL（数据库存储） |
| `student_img` | string[] | 学生答题卡图片 URL（OCR 提取） |
| `ocr_markdown` | string | OCR 服务原始输出 markdown（调试用） |

**解析模式**：

| 模式 | `paper_id` | 行为 |
|------|------------|------|
| 答题卡模式 | 传入 | 查 HugeGraph 补全题目/标准答案/知识点/图片 URL |
| 完整试卷模式 | 不传 | 纯 OCR 解析，从参考答案区域文本行（如 `1. C`）提取答案 |

**解析逻辑**：
- **选择题**：从答题卡 `<table>` 提取学生选项，从参考答案 `<table>` 提取标准答案
- **填空题**：从参考答案区域文本行（如 `9. (3,-2)`）提取标准答案
- **解答题**：标准答案为 null，需人工评阅
- **图片 URL**：从题目内容中的 `<img src="...">` 标签提取，MinIO 预签名 URL 有时效性

## 试题语义搜索

```
POST /api/edu/search/questions
```

基于 Milvus 的 Dense + BM25 混合检索，支持按知识点层级过滤。

**请求**：

```json
{
  "query": "求二次函数的最值",
  "kp_level": 2,
  "kp_name": "函数",
  "limit": 10
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 自然语言查询文本 |
| `kp_level` | int | 否 | 知识点层级过滤（1-4），需与 `kp_name` 一起使用 |
| `kp_name` | string | 否 | 知识点名称过滤，需与 `kp_level` 一起使用 |
| `limit` | int | 否 | 返回条数（1-100），默认 10 |

**响应**：

```json
{
  "query": "求二次函数的最值",
  "kp_filter": "level_2=函数",
  "hits": [
    {
      "question_id": "question_abc123...",
      "paper_id": "paper_xyz...",
      "number": "15",
      "content": "已知二次函数 f(x)=x²-4x+3...",
      "question_type": "解答题",
      "kp_names_l1": ["代数"],
      "kp_names_l2": ["函数"],
      "kp_names_l3": ["二次函数"],
      "kp_names_l4": ["二次函数最值"]
    }
  ],
  "total": 1
}
```

> **依赖**：需配置 Embedding 服务（`EMBED_BASE_URL`）并确保 Milvus 可用，否则返回 503。

## 幂等性

试卷顶点 ID 格式 `paper_{md5(object_key)}`，题目顶点 ID 格式 `question_{md5(object_key:题号)}`。同一份 MinIO 文件每次抽取产生相同的顶点 ID，HugeGraph 主键冲突自动跳过，不会重复创建顶点或边。

## 运行测试

```bash
# 全部测试
python -m pytest tests/ -v

# 仅单元测试
python -m pytest tests/unit/ -v

# 仅集成测试
python -m pytest tests/integration/ -v
```

## Docker 部署

详见 `deploy.md`，简要步骤：

### 构建镜像（Mac ARM → Linux x86_64）

```bash
docker buildx build --platform linux/amd64 -t exam-extract:1.1 -o type=docker .
docker save exam-extract:1.1 | gzip > exam-extract.tar.gz
```

### 部署到服务器

```bash
scp exam-extract.tar.gz docker-compose.prod.yml .env.prod root@<server>:/ssd2/EducationKnowledgePackage/
ssh root@<server>
cd /ssd2/EducationKnowledgePackage
gunzip -c exam-extract.tar.gz | docker load
docker compose -f docker-compose.prod.yml --env-file .env.prod down
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
curl http://127.0.0.1:8085/health
```

生产环境使用 `network_mode: host`，API 直接监听宿主机 **8085** 端口。

## 设计要点

- **LLM 不输出物理 id**：只输出候选知识点名称，避免模型编造不存在的 ID。
- **匹配逻辑由代码控制**：严格精确匹配为主，embedding 语义匹配为兜底，保证所有 `examines` 边的目标都是已有四级知识点。
- **向量双写**：抽取时间步将题目和知识点写入 Milvus（dense + BM25 稀疏向量），支持后续语义搜索。
- **幂等导入**：确定性 ID 保证重复导入不产生重复数据。
- **未命中可追溯**：所有未匹配候选进入 `unmatched` 列表并落盘，便于人工复核。
- **中间产物先于导入**：产物在导入 HugeGraph 之前写入磁盘，即使导入失败也能保留审计材料。
- **启动自检**：应用启动时自动校验 Embedding 服务维度与 Milvus schema 一致性，不匹配时告警但不阻断启动。
