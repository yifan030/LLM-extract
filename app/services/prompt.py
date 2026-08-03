# -*- coding: utf-8 -*-
"""Prompt 构建服务。"""
import os

from app.repositories.hugegraph import HugeGraphRepository


class PromptService:
    def __init__(self, hg_repo: HugeGraphRepository):
        self._hg_repo = hg_repo

    async def build_prompt(self, markdown_content: str) -> str:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        prompt_path = os.path.join(base_dir, "prompts", "exam_extract.md")
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()

        level4_names = await self._hg_repo.load_level4_names()
        names_text = "\n".join(f"- {name}" for name in sorted(level4_names))
        return (
            template.replace("{{level_4_knowledge_points}}", names_text)
            .replace("{{markdown_content}}", markdown_content)
        )

    def build_prompt_sync(self, markdown_content: str, level4_names: list[str]) -> str:
        """同步版本：CLI 场景使用，传入已加载的知识点列表避免 async 依赖。"""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        prompt_path = os.path.join(base_dir, "prompts", "exam_extract.md")
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()
        names_text = "\n".join(f"- {name}" for name in sorted(level4_names))
        return (
            template.replace("{{level_4_knowledge_points}}", names_text)
            .replace("{{markdown_content}}", markdown_content)
        )
