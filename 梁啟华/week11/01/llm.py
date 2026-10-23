"""大模型客户端封装。

默认使用 DashScope（阿里云百炼）的 OpenAI 兼容接口，
可以通过环境变量覆盖：

    OPENAI_API_KEY   API Key
    OPENAI_BASE_URL  接口地址
    SQL_AGENT_MODEL  模型名称（默认 qwen-max）
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from openai import AuthenticationError, OpenAI

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-max"


class LLMClient:
    """OpenAI 兼容接口的轻量封装，带重试与 JSON 解析。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_retries: int = 3,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "未配置大模型 API Key，请先设置环境变量 OPENAI_API_KEY"
                "（DashScope/阿里云百炼：https://bailian.console.aliyun.com/）"
            )
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URL
        self.model = model or os.getenv("SQL_AGENT_MODEL") or DEFAULT_MODEL
        self.temperature = temperature
        self.max_retries = max_retries
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
            max_retries=0,
        )

    def chat(self, messages: list[dict[str, str]], temperature: float | None = None) -> str:
        """调用大模型并返回文本内容，失败时按指数退避重试。"""
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature if temperature is None else temperature,
                )
                content = completion.choices[0].message.content
                if content is None:
                    raise ValueError("模型返回内容为空")
                return content.strip()
            except AuthenticationError as exc:
                logger.error(
                    "大模型 API Key 鉴权失败（HTTP 401）。请在环境变量 OPENAI_API_KEY 中"
                    "配置可用的 DashScope Key（阿里云百炼 https://bailian.console.aliyun.com/）。"
                )
                raise RuntimeError(
                    "大模型 API Key 无效或已过期，请通过环境变量 OPENAI_API_KEY 配置正确的"
                    " DashScope API Key。仓库内置的演示 Key 已失效。"
                ) from exc
            except Exception as exc:  # noqa: BLE001 - 需要统一重试
                last_error = exc
                logger.warning(
                    "调用大模型失败（第 %s/%s 次）：%s", attempt, self.max_retries, exc
                )
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"调用大模型失败：{last_error}") from last_error

    def chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """要求模型输出 JSON，并做容错解析。"""
        text = self.chat(messages)
        return parse_json(text)


def parse_json(text: str) -> dict[str, Any]:
    """从模型输出中提取 JSON 对象，兼容 ```json 围栏和前后解释文字。"""
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", candidate, flags=re.S | re.I)
    if fence:
        candidate = fence.group(1).strip()

    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else {"value": data}
    except json.JSONDecodeError:
        pass

    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(candidate[start : end + 1])
            return data if isinstance(data, dict) else {"value": data}
        except json.JSONDecodeError:
            logger.debug("JSON 解析失败，原始输出：%s", text)

    raise ValueError(f"无法解析模型输出的 JSON：{text[:200]}")
