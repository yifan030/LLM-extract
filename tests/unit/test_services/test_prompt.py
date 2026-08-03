# -*- coding: utf-8 -*-
"""Tests for app.services.prompt.PromptService (async repository)."""
import pytest
from unittest.mock import AsyncMock

from app.services.prompt import PromptService


@pytest.mark.asyncio
async def test_build_prompt_replaces_placeholders():
    mock_hg = AsyncMock()
    mock_hg.load_level4_names.return_value = ["交集", "子集"]
    svc = PromptService(mock_hg)
    result = await svc.build_prompt("## 试卷内容")

    assert "交集" in result
    assert "子集" in result
    assert "## 试卷内容" in result
    assert "{{level_4_knowledge_points}}" not in result
    assert "{{markdown_content}}" not in result
    mock_hg.load_level4_names.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_prompt_sorts_level4_names():
    mock_hg = AsyncMock()
    mock_hg.load_level4_names.return_value = ["子集", "交集"]
    svc = PromptService(mock_hg)
    result = await svc.build_prompt("试卷")

    # 列表按名称排序后插入模板
    assert result.index("- 交集") < result.index("- 子集")


def test_build_prompt_sync():
    svc = PromptService.__new__(PromptService)
    result = svc.build_prompt_sync("## 测试", ["知识点A"])

    assert "知识点A" in result
    assert "## 测试" in result
    assert "{{level_4_knowledge_points}}" not in result
    assert "{{markdown_content}}" not in result
