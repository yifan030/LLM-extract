# 试卷抽取与知识点关联导入工具

从高中数学 Markdown 试卷中抽取试卷、题目、题型信息，并自动关联到 HugeGraph 知识图谱中**已有**的四级知识点，最终生成 HugeGraph 可导入的中间 JSON 并支持一键写入图库。

## 核心能力

- **Markdown 试卷解析**：读取试卷 Markdown，保留 LaTeX 公式。
- **LLM 自动抽取**：支持 OpenAI-compatible API（OpenAI、DeepSeek、Qwen、Moonshot、vLLM 等），自动抽取题目与候选四级知识点。
- **严格知识点对齐**：将 LLM 给出的候选知识点名称与 HugeGraph 中已有的四级知识点精确匹配，未命中项进入 `unmatched` 报告，不新建知识点。
- **HugeGraph 导入**：自动创建 `exam_paper`、`question` 顶点及 `contains`、`belongs_to_type`、`examines` 边，已存在顶点会跳过并计数。
- **雪花 ID**：`exam_paper_id` 与 `question_id` 使用雪花算法生成，保证全局唯一。

## 项目结构

```text
.
├── exam_extract/              # 主包
│   ├── __init__.py
│   ├── cli.py                 # 命令行入口（一键脚本）
│   ├── llm.py                 # OpenAI-compatible LLM 客户端
│   ├── prompt.py              # Prompt 生成与四级知识点加载
│   ├── matcher.py             # 候选知识点严格匹配
│   ├── adapter.py             # HugeGraph REST API 导入
│   ├── models.py              # Pydantic 模型
│   ├── logger.py              # 日志 fallback
│   └── README.md              # 模块级说明
├── prompts/
│   └── exam_extract.md        # LLM Prompt 模板
├── tests/                     # 测试集
├── reference/                 # 试卷样例与参考数据
├── docs/superpowers/          # 设计文档与实施计划
├── requirements.txt
└── README.md                  # 本文件
```

## 安装

```bash
cd /Users/edy/Documents/llm-extract-question
pip install -r requirements.txt
```

依赖：`pydantic>=2.0`、`requests>=2.28.0`、`openai>=1.0`。

## 快速开始（一键模式）

设置 LLM API key 后，一条命令完成全流程：

```bash
export LLM_API_KEY=sk-...
# 可选：使用非 OpenAI 的 OpenAI-compatible 服务
export LLM_BASE_URL=https://api.deepseek.com/v1
export LLM_MODEL=deepseek-chat

python -m exam_extract.cli \
  --markdown reference/24-01-20高一数课堂资料（模拟卷）.md \
  --output tmp/exam_result.json \
  --import-to-hg
```

命令执行流程：

1. 从 HugeGraph 加载 591 个四级知识点名称。
2. 自动生成 Prompt 并调用 LLM。
3. 将 LLM 返回保存为 `tmp/24-01-20高一数课堂资料（模拟卷）.llm.json`。
4. 严格匹配候选知识点，生成中间 JSON。
5. 将中间 JSON 导入 HugeGraph，打印导入报告。

### CLI 参数说明

| 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `--markdown` | - | 必填 | 试卷 Markdown 文件路径 |
| `--output` | - | 必填 | 中间 JSON 输出路径 |
| `--host` | - | `202.107.249.39` | HugeGraph 主机 |
| `--port` | - | `50045` | HugeGraph 端口 |
| `--user` | - | `admin` | HugeGraph 用户名 |
| `--passwd` | - | `admin` | HugeGraph 密码 |
| `--graphspace` | - | `DEFAULT` | HugeGraph graphspace |
| `--graph` | - | `edu` | HugeGraph 图名 |
| `--import-to-hg` | - | 否 | 是否直接导入 HugeGraph |
| `--llm-api-key` | `LLM_API_KEY` / `OPENAI_API_KEY` | `None` | LLM API key，存在则自动调用 LLM |
| `--llm-base-url` | `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible 接口地址 |
| `--llm-model` | `LLM_MODEL` | `gpt-4o` | 模型名 |
| `--llm-temperature` | - | `0.0` | 采样温度 |
| `--llm-max-tokens` | - | `8192` | 最大输出 token |
| `--llm-timeout` | - | `120.0` | LLM 调用超时秒数 |

## 手动模式（两步走）

如果不提供 `--llm-api-key`，CLI 会生成 Prompt 并提示你手动将 LLM 输出保存为同名 `.llm.json`：

```bash
# 第 1 步：生成 Prompt 并提示保存 LLM 输出
python -m exam_extract.cli \
  --markdown reference/24-01-20高一数课堂资料（模拟卷）.md \
  --output tmp/exam_result.json

# 按终端提示，将 LLM 输出保存为：
# reference/24-01-20高一数课堂资料（模拟卷）.llm.json

# 第 2 步：读取 .llm.json 并导入 HugeGraph
python -m exam_extract.cli \
  --markdown reference/24-01-20高一数课堂资料（模拟卷）.md \
  --output tmp/exam_result.json \
  --import-to-hg
```

## 运行测试

```bash
python -m pytest tests/ -v
```

当前测试覆盖：模型校验、Prompt 生成、严格匹配、HugeGraph Adapter、LLM 客户端、CLI 自动/手动分支。

## 流水线架构

```text
Markdown 试卷
     │
     ▼
┌─────────────────────┐
│  Prompt 生成 + 知识点加载  │  exam_extract/prompt.py
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  LLM 自动抽取（可选）      │  exam_extract/llm.py
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  候选知识点严格匹配        │  exam_extract/matcher.py
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  中间 JSON（vertices/edges/unmatched） │  exam_extract/models.py
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  HugeGraph REST API 导入  │  exam_extract/adapter.py
└─────────────────────┘
```

## 设计要点

- **LLM 不输出物理 id**：只输出候选知识点名称，避免模型编造不存在的 `level_4_xxx`。
- **匹配逻辑由代码控制**：严格精确匹配，保证所有 `examines` 边的目标都是已有四级知识点。
- **幂等导入**：重复导入同一试卷时，已存在顶点会被跳过，不会破坏已有数据。
- **未命中可追溯**：所有未匹配候选进入 `unmatched` 列表，便于人工复核。

## 相关文档

- 设计文档：`docs/superpowers/specs/2026-08-01-exam-knowledge-point-linking-design.md`
- 实施计划：`docs/superpowers/plans/2026-08-02-exam-knowledge-point-linking-plan.md`
- 模块说明：`exam_extract/README.md`
