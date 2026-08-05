# -*- coding: utf-8 -*-
"""LLM 调用服务 — 基于 AsyncOpenAI。"""
import json
import re
from dataclasses import dataclass

from openai import AsyncOpenAI
from pydantic import ValidationError

from conf.config import Settings
from core.exceptions import LlmApiCallError
from logs.logging import get_logger
from model.models import LlmExtractResult

log = get_logger(__name__)


@dataclass
class LlmConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    temperature: float = 0.0
    max_tokens: int = 8192
    timeout: float = 120.0


class LlmService:
    def __init__(self, settings: Settings):
        self._config = LlmConfig(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout,
        )
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                timeout=self._config.timeout,
            )
        return self._client

    async def extract(self, prompt: str) -> LlmExtractResult:
        raw = await self._call_llm(prompt)
        payload = self._extract_json_payload(raw)
        try:
            return LlmExtractResult.model_validate(payload)
        except ValidationError as exc:
            raise LlmApiCallError(f"LLM 输出结构校验失败: {exc}") from exc

    async def _call_llm(self, prompt: str, max_tokens: int | None = None) -> str:
        """调用 LLM，当输出因长度截断时自动以更大 ``max_tokens`` 重试一次。"""
        if max_tokens is None:
            max_tokens = self._config.max_tokens

        try:
            response = await self.client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": "你是高中数学试卷信息抽取助手，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=self._config.temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            raise LlmApiCallError(f"LLM API 调用失败: {exc}") from exc

        choice = response.choices[0]
        content = choice.message.content
        if content is None:
            raise LlmApiCallError("LLM 返回内容为空")

        if getattr(choice, "finish_reason", None) == "length":
            # 自动扩容重试一次
            next_tokens = max_tokens * 2
            limit = 32768
            if next_tokens <= limit:
                log.warning(
                    "LLM 输出截断 (max_tokens=%d)，自动扩容重试 (max_tokens=%d)",
                    max_tokens, next_tokens,
                )
                return await self._call_llm(prompt, max_tokens=next_tokens)
            log.error("LLM 输出截断且已达上限 (max_tokens=%d)", max_tokens)
            raise LlmApiCallError(
                f"LLM 输出因长度被截断 (max_tokens={max_tokens}，已达上限)"
            )

        return content

    @staticmethod
    def _extract_json_payload(text: str) -> dict:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError as exc:
                raise LlmApiCallError(f"代码围栏内不是合法 JSON: {exc}") from exc

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        log.error("LLM 原始输出 (前500字符): %s", text[:500])
        raise LlmApiCallError("无法从 LLM 输出中解析出 JSON")
