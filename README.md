# 试卷抽取与知识点关联导入工具

从高中数学 Markdown 试卷中抽取试卷、题目、题型信息，并自动关联到 HugeGraph 知识图谱中**已有**的四级知识点，最终生成 HugeGraph 可导入的中间 JSON 并支持一键写入图库。

## 核心能力

- **Markdown 试卷解析**：从 MinIO 读取试卷 Markdown，保留 LaTeX 公式。
- **LLM 自动抽取**：支持 OpenAI-compatible API（OpenAI、DeepSeek、Qwen 等），自动抽取题目与候选四级知识点。
- **严格知识点对齐**：将 LLM 给出的候选知识点名称与 HugeGraph 中已有的四级知识点精确匹配，未命中项进入 `unmatched` 报告，不新建知识点。
- **幂等导入**：试卷和题目的顶点 ID 由源文件路径确定性派生（MD5），重复导入同一份试卷时 HugeGraph 自动跳过已存在顶点和边，不会产生重复数据。
- **中间产物审计**：支持将 LLM 原始输出和匹配后的中间 JSON 落盘，人工复核 `unmatched` 清单后再导入。
- **雪花 ID**：CLI 工具保留雪花 ID 生成器，供其他工具链使用。

## 项目结构

```text
.
├── main.py                     # FastAPI 应用入口
├── cli.py                      # 命令行入口
├── bin/                        # 启动/部署脚本
├── conf/                       # 配置
│   └── config.py               # pydantic-settings 配置中心
├── core/                       # 基础机制
│   ├── exceptions.py           # 统一异常定义
│   └── events.py               # Redis Streams 消费者
├── libs/                       # 外部系统封装
│   ├── hugegraph.py            # HugeGraph REST API 封装
│   └── minio.py                # MinIO 异步 SDK 封装
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
│   ├── matcher.py              # 知识点严格匹配
│   ├── minio.py                # MinIO 文件浏览服务
│   ├── prompt.py               # Prompt 构建
│   └── scoring.py              # OCR markdown 解析（判分）
├── utils/                      # 通用工具
│   ├── snowflake.py            # 简易雪花 ID 生成器
│   └── paths.py                # 项目路径管理
├── logs/                       # 日志配置
│   └── logging.py
├── prompts/                    # LLM Prompt 模板
├── tests/                      # 测试集
├── reference/                  # 参考资料
├── docs/                       # 文档
├── requirements.txt
└── README.md
```

## 安装

```bash
cd /Users/edy/Documents/llm-extract-question
pip install -r requirements.txt
```

## 配置

在项目根目录创建 `.env`：

```env
# LLM
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_MAX_TOKENS=16384

# MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=llm-construct

# Redis
REDIS_URL=redis://localhost:6379/0

# HugeGraph
HG_HOST=202.107.249.39
HG_PORT=50045
HG_USER=admin
HG_PASSWD=admin
```

所有配置项支持环境变量覆盖，详见 `conf/config.py`。

## 快速开始

### 方式一：Web API

启动服务：

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

**审计模式（推荐）：先抽取落盘，人工复核后再导入**

```bash
# 第 1 步：仅抽取 + 保存产物，不入库
curl -X POST http://localhost:8080/api/v1/extract \
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
curl -X POST http://localhost:8080/api/v1/extract \
  -H 'Content-Type: application/json' \
  -d '{"object_key":"education/uploads/.../模拟卷.md",
       "save_artifacts":false, "import_to_hg":true}'
```

> 第二次运行 paper_id 相同，HugeGraph 侧幂等跳过已存在的顶点和边。

**直接导入模式（跳过审计）**

```bash
# 默认行为：save_artifacts=false, import_to_hg=true
curl -X POST http://localhost:8080/api/v1/extract \
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
| `POST` | `/api/v1/extract` | 试卷抽取（支持审计/导入模式） |
| `GET` | `/api/v1/minio/files` | MinIO `.md` 文件列表 |
| `POST` | `/api/v1/minio/webhook/minio` | MinIO bucket 事件回调 |
| `GET` | `/api/v1/knowledge` | 四级知识点列表 |
| `GET` | `/api/v1/knowledge/{kp_id}` | 单个知识点详情 |
| `GET` | `/api/v1/papers` | 已导入试卷列表 |
| `GET` | `/api/v1/papers/{paper_id}` | 试卷详情 |
| `GET` | `/api/v1/papers/{paper_id}/questions` | 试卷题目列表 |
| `GET` | `/api/v1/questions/{question_id}` | 题目详情 |
| `POST` | `/api/v1/scoring/parse` | OCR markdown 解析为判分 JSON（不走 LLM） |

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
POST /api/v1/scoring/parse
```

将 OCR 输出的试卷 markdown 解析为结构化 JSON，纯规则解析不走 LLM。用于提取学生作答与标准答案，供后续判分流程使用。

**请求**：

```json
{
  "markdown": "<OCR 输出的完整 markdown 文本>",
  "paper_id": "paper_890e5428fd13..."
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `markdown` | string | 是 | OCR 输出的 markdown 文本 |
| `paper_id` | string | 是 | 试卷 ID，用于从 HugeGraph 查询标准答案 |

**响应**：

```json
{
  "paper_title": "长郡中学 2023 级高一入学检测试卷",
  "paper_id": "paper_890e5428fd13...",
  "total_score": 100,
  "sections": [
    {
      "type": "选择题",
      "score_per_question": 4,
      "questions": [
        {
          "number": "1",
          "content": "已知 a 是 √13 的小数部分...",
          "image_urls": [
            "http://minio:9000/.../img.jpg?X-Amz-..."
          ],
          "student_answer": "B",
          "standard_answer": "B",
          "knowledge_points": []
        }
      ]
    },
    {
      "type": "填空题",
      "score_per_question": 4,
      "questions": [
        {
          "number": "9",
          "content": "点 P 关于原点的对称点为 ___.",
          "image_urls": [],
          "student_answer": null,
          "standard_answer": "(3,-2)",
          "knowledge_points": []
        }
      ]
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `number` | string | 题号 |
| `content` | string | 题目内容（含 LaTeX、HTML 图片标签） |
| `image_urls` | string[] | 题目中的图片 URL 列表 |
| `student_answer` | string\|null | 从答题卡表格提取的学生作答 |
| `standard_answer` | string\|null | 标准答案，优先查 HugeGraph，否则从参考答案区域提取 |
| `knowledge_points` | string[] | 关联知识点，预留字段由后续流程填充 |
| `score_per_question` | int\|null | 该题型每题原始分值，从 section 标题提取 |

**解析逻辑**：
- **选择题**：从答题卡 `<table>` 提取学生选项，从参考答案 `<table>` 提取标准答案
- **填空题**：从参考答案区域文本行（如 `9. (3,-2)`）提取标准答案
- **解答题**：标准答案为 null，需人工评阅
- **图片 URL**：从题目内容中的 `<img src="...">` 标签提取，MinIO 预签名 URL 有时效性

## 幂等性

试卷顶点 ID 格式 `paper_{md5(object_key)}`，题目顶点 ID 格式 `question_{md5(object_key:题号)}`。同一份 MinIO 文件每次抽取产生相同的顶点 ID，HugeGraph 主键冲突自动跳过，不会重复创建顶点或边。

## 运行测试

```bash
python -m pytest tests/ -v
```

## 设计要点

- **LLM 不输出物理 id**：只输出候选知识点名称，避免模型编造不存在的 ID。
- **匹配逻辑由代码控制**：严格精确匹配，保证所有 `examines` 边的目标都是已有四级知识点。
- **幂等导入**：确定性 ID 保证重复导入不产生重复数据。
- **未命中可追溯**：所有未匹配候选进入 `unmatched` 列表并落盘，便于人工复核。
- **中间产物先于导入**：产物在导入 HugeGraph 之前写入磁盘，即使导入失败也能保留审计材料。
