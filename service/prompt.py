# -*- coding: utf-8 -*-
"""Prompt 构建服务。"""
import os

from logs.logging import get_logger

log = get_logger(__name__)


def _project_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_level4_names() -> list[str]:
    """从静态清单文件加载四级知识点名称，避免每次抽取查询 HugeGraph。

    清单文件 ``prompts/level4_knowledge_points.txt`` 每行一个知识点名称，
    由 ``bin/dump_kp_names.py`` 从 HugeGraph 导出生成。
    """
    path = os.path.join(_project_dir(), "prompts", "level4_knowledge_points.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            names = [line.strip() for line in f if line.strip()]
        log.info("已加载 %d 个四级知识点（来自 %s）", len(names), path)
        return names
    except FileNotFoundError:
        log.error("四级知识点清单文件不存在: %s", path)
        return []


class PromptService:
    """Prompt 构建服务（无外部依赖，知识点从静态文件加载）。"""

    def __init__(self, hg_repo=None):  # hg_repo 保留参数以兼容旧调用方，已不再使用
        pass

    async def build_prompt(self, markdown_content: str) -> str:
        """异步构建 prompt（兼容旧接口，内部委托给同步方法）。"""
        level4_names = load_level4_names()
        return self._render(markdown_content, level4_names)

    def build_prompt_sync(self, markdown_content: str, level4_names: list[str] | None = None) -> str:
        """构建 prompt。level4_names 可选，为空时自动从静态文件加载。"""
        if level4_names is None:
            level4_names = load_level4_names()
        return self._render(markdown_content, level4_names)

    @staticmethod
    def _render(markdown_content: str, level4_names: list[str]) -> str:
        prompt_path = os.path.join(_project_dir(), "prompts", "exam_extract.md")
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()
        names_text = "\n".join(f"- {name}" for name in sorted(level4_names))
        return (
            template.replace("{{level_4_knowledge_points}}", names_text)
            .replace("{{markdown_content}}", markdown_content)
        )
