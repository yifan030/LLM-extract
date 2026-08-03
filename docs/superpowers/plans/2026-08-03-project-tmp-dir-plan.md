# 项目级 tmp 目录改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 CLI 产生的 `.llm.json` 与默认 `--output` 中间 JSON 统一放到项目根目录下的 `tmp/` 中，并自动创建该目录。

**Architecture:** 新增 `exam_extract/paths.py` 集中管理项目根目录、临时目录和中间产物路径；`cli.py` 调用该模块计算 `.llm.json` 与默认 `--output` 路径；文档与测试同步更新；`tmp/` 加入 `.gitignore`。

**Tech Stack:** Python 3.x，标准库 `os`，现有测试框架 `pytest`。

## Global Constraints

- 中间产物必须放在项目根目录的 `tmp/` 下，不使用系统 `/tmp/`。
- `.llm.json` 位置改为 `tmp/<stem>.llm.json`，其中 `<stem>` 为 markdown 文件名去掉 `.md`。
- `--output` 默认值改为 `tmp/<stem>.intermediate.json`，用户显式传入时仍优先使用用户值。
- CLI 运行时自动创建 `tmp/`（不存在时）。
- `tmp/` 加入 `.gitignore`，不提交到版本控制。
- 不兼容旧位置 `.llm.json`，只在新位置读写。
- 所有改动必须通过 `python -m pytest tests/ -v`。

---

### Task 1: 新增路径管理模块 `exam_extract/paths.py`

**Files:**
- Create: `exam_extract/paths.py`

**Interfaces:**
- Produces:
  - `get_project_root() -> str`
  - `get_tmp_dir() -> str`
  - `get_llm_output_path(markdown_path: str) -> str`
  - `get_default_output_path(markdown_path: str) -> str`

- [ ] **Step 1: 编写失败测试**

```python
# tests/test_paths.py
import os

import pytest

from exam_extract import paths


def test_get_project_root_finds_readme(monkeypatch, tmp_path):
    fake_root = tmp_path / "fake_project"
    fake_root.mkdir()
    (fake_root / "README.md").write_text("# fake", encoding="utf-8")
    monkeypatch.setattr(paths, "__file__", str(fake_root / "exam_extract" / "paths.py"))
    assert paths.get_project_root() == str(fake_root)


def test_get_tmp_dir_auto_creates(monkeypatch, tmp_path):
    fake_root = tmp_path / "fake_project"
    fake_root.mkdir()
    (fake_root / "README.md").write_text("# fake", encoding="utf-8")
    monkeypatch.setattr(paths, "get_project_root", lambda: str(fake_root))
    result = paths.get_tmp_dir()
    assert result == str(fake_root / "tmp")
    assert os.path.isdir(result)


def test_get_llm_output_path(monkeypatch, tmp_path):
    fake_root = tmp_path / "fake_project"
    fake_root.mkdir()
    monkeypatch.setattr(paths, "get_tmp_dir", lambda: str(fake_root / "tmp"))
    assert paths.get_llm_output_path("/some/where/试卷.md") == str(fake_root / "tmp" / "试卷.llm.json")


def test_get_default_output_path(monkeypatch, tmp_path):
    fake_root = tmp_path / "fake_project"
    fake_root.mkdir()
    monkeypatch.setattr(paths, "get_tmp_dir", lambda: str(fake_root / "tmp"))
    assert paths.get_default_output_path("/some/where/试卷.md") == str(fake_root / "tmp" / "试卷.intermediate.json")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_paths.py -v`

Expected: FAIL，提示模块或函数不存在。

- [ ] **Step 3: 实现最小路径模块**

```python
# exam_extract/paths.py
import os


def get_project_root() -> str:
    """从当前文件向上查找项目根目录。

    项目根目录的判定：存在 README.md 且不存在 __init__.py（避免把包目录误判为根）。
    """
    current = os.path.dirname(os.path.abspath(__file__))
    while True:
        has_readme = os.path.exists(os.path.join(current, "README.md"))
        is_package = os.path.exists(os.path.join(current, "__init__.py"))
        if has_readme and not is_package:
            return current
        parent = os.path.dirname(current)
        if parent == current:
            raise RuntimeError(f"无法找到项目根目录（未找到 README.md）: {current}")
        current = parent


def get_tmp_dir() -> str:
    """返回项目根目录下的 tmp/，不存在时自动创建。"""
    tmp_dir = os.path.join(get_project_root(), "tmp")
    try:
        os.makedirs(tmp_dir, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"无法创建临时目录 {tmp_dir}: {exc}") from exc
    return tmp_dir


def _markdown_stem(markdown_path: str) -> str:
    return os.path.splitext(os.path.basename(markdown_path))[0]


def get_llm_output_path(markdown_path: str) -> str:
    """返回 LLM 原始输出应保存的路径：tmp/<stem>.llm.json。"""
    return os.path.join(get_tmp_dir(), f"{_markdown_stem(markdown_path)}.llm.json")


def get_default_output_path(markdown_path: str) -> str:
    """返回默认的中间 JSON 输出路径：tmp/<stem>.intermediate.json。"""
    return os.path.join(get_tmp_dir(), f"{_markdown_stem(markdown_path)}.intermediate.json")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_paths.py -v`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add exam_extract/paths.py tests/test_paths.py
git commit -m "feat: add project-level tmp path helpers"
```

---

### Task 2: 添加 `.gitignore` 忽略 `tmp/`

**Files:**
- Create: `.gitignore`

**Interfaces:**
- Produces: `.gitignore` 文件，包含 `tmp/`。

- [ ] **Step 1: 创建 `.gitignore`**

```text
# 项目中间产物
tmp/

# Python
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/

# IDE
.vscode/
.idea/
.DS_Store
```

- [ ] **Step 2: 验证未跟踪但忽略**

Run:
```bash
git check-ignore -v tmp/dummy.json
```

Expected: 输出匹配 `.gitignore` 中的 `tmp/` 规则。

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore project tmp directory"
```

---

### Task 3: 改造 `exam_extract/cli.py` 使用新的路径模块

**Files:**
- Modify: `exam_extract/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `exam_extract.paths.get_tmp_dir`, `get_llm_output_path`, `get_default_output_path`
- Produces: `.llm.json` 与默认 `--output` 均写入 `tmp/`

- [ ] **Step 1: 修改 `parse_args` 让 `--output` 默认值为 `None`**

```python
# exam_extract/cli.py
# 导入新增模块
from exam_extract import paths

# ...

def parse_args():
    parser = argparse.ArgumentParser(description="试卷抽取并导入 HugeGraph")
    parser.add_argument("--markdown", required=True, help="试卷 markdown 文件路径")
    parser.add_argument(
        "--output",
        default=None,
        help="中间 JSON 输出路径（默认：tmp/<stem>.intermediate.json）",
    )
    # ... 其余参数不变
    return parser.parse_args()
```

- [ ] **Step 2: 在 `main()` 中应用默认路径并确保 tmp 目录存在**

```python
def main():
    args = parse_args()

    # 确保项目 tmp 目录存在
    paths.get_tmp_dir()

    if args.output is None:
        args.output = paths.get_default_output_path(args.markdown)

    llm_output_path = paths.get_llm_output_path(args.markdown)

    # 后续逻辑不变，只把原来硬编码的 llm_output_path 替换为上面的变量
```

替换前原有代码：
```python
llm_output_path = args.markdown.replace(".md", ".llm.json")
```
改为：
```python
llm_output_path = paths.get_llm_output_path(args.markdown)
```

- [ ] **Step 3: 更新 CLI 测试以使用隔离的 tmp 目录**

修改 `tests/test_cli.py`，在每个测试开头 monkeypatch `exam_extract.paths.get_tmp_dir` 到 `tmp_path`，避免写入真实项目 `tmp/`。

在三个测试函数开头都加入：

```python
monkeypatch.setattr("exam_extract.paths.get_tmp_dir", lambda: str(tmp_path))
```

同时更新 `llm_json_path` 变量：

```python
llm_json_path = tmp_path / "paper.llm.json"
```

`test_auto_mode_api_failure_exits_without_writing_files` 中也做同样更新。

- [ ] **Step 4: 运行 CLI 测试**

Run: `pytest tests/test_cli.py -v`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add exam_extract/cli.py tests/test_cli.py
git commit -m "feat: use project tmp dir for llm json and default output"
```

---

### Task 4: 更新文档中的示例路径

**Files:**
- Modify: `README.md`
- Modify: `exam_extract/README.md`
- Modify: `docs/superpowers/plans/2026-08-02-exam-knowledge-point-linking-plan.md`

**Interfaces:**
- Produces: 所有示例从 `--output /tmp/...` 改为 `--output tmp/...`；手动模式提示保存位置改为 `tmp/...`。

- [ ] **Step 1: 更新 `README.md`**

将三处：
```bash
--output /tmp/exam_result.json
```
改为：
```bash
--output tmp/exam_result.json
```

在手动模式说明中，把：
```text
将 LLM 返回保存为 `reference/24-01-20高一数课堂资料（模拟卷）.llm.json`。
```
改为：
```text
将 LLM 返回保存为 `tmp/24-01-20高一数课堂资料（模拟卷）.llm.json`。
```

- [ ] **Step 2: 更新 `exam_extract/README.md`**

将：
```bash
--output /tmp/exam_result.json
```
全部改为：
```bash
--output tmp/exam_result.json
```

将手动模式说明：
```text
按提示保存 LLM 输出为 reference/24-01-20高一数课堂资料（模拟卷）.llm.json
```
改为：
```text
按提示保存 LLM 输出为 tmp/24-01-20高一数课堂资料（模拟卷）.llm.json
```

- [ ] **Step 3: 更新 `docs/superpowers/plans/2026-08-02-exam-knowledge-point-linking-plan.md`**

修改第 852 行、976 行、983 行的：
```bash
--output /tmp/exam_result.json
```
为：
```bash
--output tmp/exam_result.json
```

并更新该计划 Task 7 中第 978 行的提示文字：
```text
将生成的 Prompt 发送给 LLM，保存返回 JSON 为同名的 `.llm.json` 文件。
```
可补充为：
```text
将生成的 Prompt 发送给 LLM，保存返回 JSON 为 `tmp/<stem>.llm.json`。
```

- [ ] **Step 4: Commit**

```bash
git add README.md exam_extract/README.md docs/superpowers/plans/2026-08-02-exam-knowledge-point-linking-plan.md
git commit -m "docs: update examples to use project tmp directory"
```

---

### Task 5: 运行全量测试并验证 CLI

**Files:**
- 无需修改文件，仅验证。

- [ ] **Step 1: 运行全部测试**

Run:
```bash
python -m pytest tests/ -v
```

Expected: 全部 PASS。

- [ ] **Step 2: 手动验证 CLI 路径行为**

Run（无需真实 LLM key，验证手动模式提示路径）：
```bash
python -m exam_extract.cli --markdown reference/24-01-20高一数课堂资料（模拟卷）.md
```

Expected: 终端提示 LLM 输出保存到 `tmp/24-01-20高一数课堂资料（模拟卷）.llm.json`，且项目根目录出现 `tmp/`。

- [ ] **Step 3: 验证 `tmp/` 被 Git 忽略**

Run:
```bash
git status
```

Expected: `tmp/` 下的文件不显示为未跟踪文件。

- [ ] **Step 4: Commit（如有测试夹具等额外改动）**

```bash
git add -A
git commit -m "test: verify project tmp dir integration"
```

---

## Spec Coverage Check

| 需求 | 对应任务 |
|---|---|
| 项目根目录新建 `tmp/` 存放中间产物 | Task 1、Task 2 |
| `.llm.json` 放到 `tmp/<stem>.llm.json` | Task 1、Task 3 |
| `--output` 默认 `tmp/<stem>.intermediate.json`，可被覆盖 | Task 3 |
| CLI 自动创建 `tmp/` | Task 1、Task 3 |
| `tmp/` 加入 `.gitignore` | Task 2 |
| 不兼容旧位置 `.llm.json` | Task 3（直接读取新路径） |
| 测试与文档同步更新 | Task 3、Task 4、Task 5 |

## Placeholder Scan

- 无 `TBD`、`TODO`、"implement later"。
- 无 "add appropriate error handling" 等模糊描述。
- 所有代码步骤均给出可直接使用的代码片段。
- 测试命令与预期结果明确。

## Type Consistency

- `get_project_root()` / `get_tmp_dir()` / `get_llm_output_path()` / `get_default_output_path()` 签名在 Task 1 和 Task 3 中保持一致。
- `paths.get_tmp_dir()` 在 Task 3 中同时承担“返回路径”和“自动创建”职责，与 Task 1 实现一致。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-03-project-tmp-dir-plan.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
