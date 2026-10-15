"""语种识别 + 翻译助手（基于 OpenAI Agents 框架）。

输入一段文本，判断其语种：
- 非中文 -> 翻译成中文
- 中文   -> 翻译成英文

最终输出固定 JSON 结构：
    {"query_input": "...", "language": "...", "result": "..."}

用法：
    python language_agent.py "你好，世界"
    python language_agent.py "Hello, how are you?"
"""
from __future__ import annotations

import json
import os
import re
import sys

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from agents import (
    Agent,
    ModelSettings,
    Runner,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled
)

set_default_openai_api("chat_completions")
set_tracing_disabled(True)

# —— DeepSeek（OpenAI 兼容）默认配置 ——
OPENAI_BASE_URL = "https://api.deepseek.com"
OPENAI_MODEL = "deepseek-flash"


class TranslationResult(BaseModel):
    """输出结构：原始输入 / 语种 / 翻译结果。"""

    query_input: str
    language: str
    result: str


INSTRUCTIONS = """你是一个「语种识别 + 翻译」助手，严格按要求处理用户输入的文本：

1. 判断输入文本的语种，language 字段填语种名（如：中文、英文、日文、韩文、法文、德文等）。
2. 若文本不是中文，则把内容翻译成中文；若文本是中文，则翻译成英文。
3. 只输出一个 JSON 对象，字段依次为 query_input（原始文本）、language（语种名）、result（翻译结果），不要输出任何其他文字。
"""


def _extract_json(text: str) -> dict:
    """从模型输出中稳健地提取 JSON 对象。

    兼容推理模型把 JSON 包在 ```json ... ``` 代码块里、或前后附带少量说明文字的情况。
    """
    raw = text.strip()
    # 优先匹配 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    else:
        # 否则取第一个 { 到最后一个 } 之间
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]
    return json.loads(raw)


def _setup_model(model: str) -> str:
    """把默认 OpenAI 客户端指到 DeepSeek，并切换到 chat completions 协议。"""
    client = AsyncOpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", OPENAI_BASE_URL),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    set_default_openai_client(client, use_for_tracing=False)
    set_default_openai_api("chat_completions")
    return model


def detect_and_translate(text: str, model: str | None = None) -> TranslationResult:
    """调用 Agent 完成语种识别 + 翻译，返回结构化结果。

    说明：不用 ``Agent(output_type=...)`` 的结构化输出，因为那会走
    ``response_format``（json_schema），而 DeepSeek 的 chat completions 端点不支持，
    会报 "This response_format type is unavailable now"。改为让模型直接输出 JSON 文本，
    再用 ``TranslationResult``（Pydantic）校验兜底。
    """
    model = _setup_model(model or os.environ.get("OPENAI_MODEL", OPENAI_MODEL))
    agent = Agent(
        name="语言识别翻译助手",
        instructions=INSTRUCTIONS,
        model=model,
        # DeepSeek 的推理模型默认开启 thinking；关闭它让输出更干净（纯 JSON，不夹带思考过程）
        model_settings=ModelSettings(extra_body={"thinking": {"type": "disabled"}}),
    )
    result = Runner.run_sync(agent, text)
    raw = str(result.final_output)
    try:
        return TranslationResult.model_validate(_extract_json(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise RuntimeError(f"模型输出无法解析为所需 JSON：{raw!r}") from exc


def main() -> None:
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:]).strip()
    else:
        text = input("请输入要识别/翻译的文本：").strip()

    if not text:
        print("输入文本不能为空")
        sys.exit(1)

    if not os.environ.get("OPENAI_API_KEY"):
        print("请先设置环境变量 OPENAI_API_KEY（DeepSeek API Key）")
        sys.exit(1)

    out = detect_and_translate(text)
    print(json.dumps(out.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
