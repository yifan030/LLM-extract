# -*- coding: utf-8 -*-
"""Stage 1.5: 调用 OpenAI-compatible LLM 并解析返回 JSON。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic import ValidationError

from exam_extract.logger import get_logger
from exam_extract.models import LlmExtractResult

log = get_logger(__name__)


class LlmApiError(Exception):
    """LLM 调用失败或返回内容无法解析时抛出。"""


@dataclass
class LlmConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    temperature: float = 0.0
    max_tokens: int = 8192
    timeout: float = 120.0


def extract_json_payload(text: str) -> Dict[str, Any]:
    """从模型原始输出中提取 JSON 对象。

    支持：
    - 纯 JSON 字符串
    - ```json ... ``` 或 ``` ... ``` 代码围栏
    - 围栏外有少量说明文字时，尝试提取围栏内容

    任何解析失败都会抛出 :class:`LlmApiError`。
    """
    text = text.strip()

    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 代码围栏
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence_match:
        content = fence_match.group(1).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LlmApiError(f"代码围栏内内容不是合法 JSON: {exc}") from exc

    # 3. 尝试截取第一个 '{' 和最后一个 '}' 之间的内容
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise LlmApiError("无法从 LLM 输出中解析出 JSON")


def call_llm(prompt: str, config: LlmConfig, client: Optional[Any] = None) -> str:
    """调用 OpenAI-compatible chat completions 接口，返回原始 content 文本。

    `client` 可注入，便于单元测试。未注入时使用 ``openai.OpenAI`` 构造客户端。
    """
    if client is None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - 依赖正常情况下已安装
            raise LlmApiError(
                "缺少 openai 包，请执行: pip install 'openai>=1.0'"
            ) from exc
        client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
        )

    try:
        response = client.chat.completions.create(
            model=config.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是高中数学试卷信息抽取助手，只输出 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
        )
    except Exception as exc:
        raise LlmApiError(f"LLM API 调用失败: {exc}") from exc

    choice = response.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        log.warning(
            "LLM 输出因长度被截断，可尝试增大 --llm-max-tokens (当前 %d)",
            config.max_tokens,
        )

    content = choice.message.content
    if content is None:
        raise LlmApiError("LLM 返回内容为空")

    return content


def run_llm_extraction(
    prompt: str, config: LlmConfig, client: Optional[Any] = None
) -> LlmExtractResult:
    """完整调用链路：LLM -> JSON 清洗 -> Pydantic 校验。"""
    raw = call_llm(prompt, config, client=client)
    payload = extract_json_payload(raw)
    try:
        return LlmExtractResult.model_validate(payload)
    except ValidationError as exc:
        raise LlmApiError(f"LLM 输出结构校验失败: {exc}") from exc
