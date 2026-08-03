# 项目级 tmp 目录设计

## 背景

当前 CLI 会把 LLM 原始输出（`.llm.json`）放在输入 markdown 文件的同级目录，且文档示例把中间 JSON 输出到系统 `/tmp/`。用户希望所有项目中间产物统一放到项目区内的 `tmp/` 目录，便于管理并避免污染系统临时目录。

## 目标

- 在项目根目录下新建 `tmp/` 目录，存放中间产物。
- `.llm.json` 从“与 markdown 同级”改为放到 `tmp/<stem>.llm.json`（`<stem>` 为 markdown 文件名去掉 `.md`）。
- `--output` 默认值改为 `tmp/<stem>.intermediate.json`，用户仍可显式覆盖。
- CLI 运行时自动创建 `tmp/`（如果不存在）。
- `tmp/` 加入 `.gitignore`，不提交中间产物。
- 不兼容旧位置 `.llm.json`：只在新位置读写。

## 方案

采用“新增 `exam_extract/paths.py` 集中管理路径”的方案。

### 新增 `exam_extract/paths.py`

职责：集中管理项目根目录、临时目录以及中间产物路径。

提供的函数：

- `get_project_root() -> str`
  - 从当前文件向上查找项目根目录。
  - 判定条件：目录下存在 `README.md` 且不存在 `__init__.py`（避免把包目录误判为根目录）。
  - 避免硬编码相对路径。
- `get_tmp_dir() -> str`
  - 返回 `项目根目录/tmp`。
  - 若目录不存在，自动创建（含必要的父目录）。
  - 创建失败时抛出 `RuntimeError`。
- `get_llm_output_path(markdown_path: str) -> str`
  - 取 markdown 文件去掉 `.md` 后的 stem，返回 `tmp/<stem>.llm.json`。
- `get_default_output_path(markdown_path: str) -> str`
  - 取 markdown 文件去掉 `.md` 后的 stem，返回 `tmp/<stem>.intermediate.json`。

### 修改 `exam_extract/cli.py`

- 导入 `exam_extract.paths`。
- 解析 `args.markdown` 后，通过 `paths.get_llm_output_path(...)` 计算 `.llm.json` 的读写位置。
- `--output` 参数默认值改为 `paths.get_default_output_path(...)`；若用户显式传入 `--output`，仍使用用户值。
- 保留错误处理：LLM 调用失败时退出；文件写入失败时抛出异常并由 CLI 顶层捕获。

### 文档与示例

- `README.md`、`exam_extract/README.md`、`docs/superpowers/plans/2026-08-02-exam-knowledge-point-linking-plan.md` 中所有 `--output /tmp/...` 示例改为 `--output tmp/...`。
- 说明 `tmp/` 会自动创建，且不会被提交到 Git。

### 测试

- `tests/test_cli.py`：
  - 自动模式生成的 `.llm.json` 路径断言改为 `tmp/<basename>.llm.json`。
  - 手动模式找不到 `.llm.json` 的提示路径断言同步更新。
  - 增加/更新 `--output` 默认路径生效的断言。
  - 验证 `tmp/` 不存在时 CLI 会自动创建。

### 错误处理

- `get_tmp_dir()` 创建目录失败时抛出 `RuntimeError`，信息包含目标路径和失败原因。
- `cli.py` 捕获后通过 `log.error` 输出并 `sys.exit(1)`。

## 非目标

- 不引入可配置的 `--tmp-dir` 参数，保持 `tmp/` 固定。
- 不迁移旧位置的 `.llm.json`，用户需重新生成。
- 不清理 `tmp/` 内容，由用户或 `.gitignore` 处理。

## 验收标准

- [ ] `python -m exam_extract.cli --markdown reference/xxx.md --output tmp/xxx.intermediate.json` 成功运行。
- [ ] 自动模式下生成 `tmp/xxx.llm.json`。
- [ ] `--output` 不传时默认写到 `tmp/<basename>.intermediate.json`。
- [ ] 删除 `tmp/` 后再次运行 CLI，能自动重建 `tmp/`。
- [ ] `tmp/` 已在 `.gitignore` 中。
- [ ] 所有测试通过：`python -m pytest tests/ -v`。

## 相关文件

- `exam_extract/paths.py`（新增）
- `exam_extract/cli.py`
- `README.md`
- `exam_extract/README.md`
- `docs/superpowers/plans/2026-08-02-exam-knowledge-point-linking-plan.md`
- `tests/test_cli.py`
- `.gitignore`（新增或更新）
