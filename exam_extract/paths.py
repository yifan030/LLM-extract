# -*- coding: utf-8 -*-
"""项目级路径管理。

集中管理项目根目录、临时目录以及 CLI 中间产物的输出路径。
"""
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
