# exam_extract

从 markdown 试卷抽取题目并关联已有四级知识点，导入 HugeGraph。

## 一键使用（自动调用 LLM）

设置环境变量或命令行参数，即可在一条命令内完成：Prompt 生成 → LLM 抽取 → 匹配知识点 → 生成中间 JSON → 导入 HugeGraph。

```bash
export LLM_API_KEY=sk-...                 # 或 --llm-api-key
export LLM_BASE_URL=https://api.openai.com/v1  # 可选，支持 DeepSeek / Qwen / Moonshot 等
export LLM_MODEL=gpt-4o                   # 可选

python -m exam_extract.cli \
  --markdown reference/24-01-20高一数课堂资料（模拟卷）.md \
  --output tmp/exam_result.json \
  --import-to-hg
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--llm-api-key` | LLM API key，默认读取 `LLM_API_KEY` 或 `OPENAI_API_KEY` |
| `--llm-base-url` | OpenAI-compatible 接口地址 |
| `--llm-model` | 模型名称 |
| `--llm-temperature` | 默认 `0.0` |
| `--llm-max-tokens` | 默认 `8192` |
| `--llm-timeout` | 默认 `120.0` 秒 |

## 手动模式（保留原流程）

如果不提供 `--llm-api-key`，CLI 会生成 Prompt 并提示你将 LLM 输出保存为同名的 `.llm.json` 文件，再重新运行：

```bash
python -m exam_extract.cli \
  --markdown reference/24-01-20高一数课堂资料（模拟卷）.md \
  --output tmp/exam_result.json
# 按提示保存 LLM 输出为 tmp/24-01-20高一数课堂资料（模拟卷）.llm.json

python -m exam_extract.cli \
  --markdown reference/24-01-20高一数课堂资料（模拟卷）.md \
  --output tmp/exam_result.json \
  --import-to-hg
```

## 测试

```bash
pytest tests/ -v
```
