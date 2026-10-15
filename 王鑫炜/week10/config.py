"""两项作业共用的模型配置。"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from agents import OpenAIChatCompletionsModel, set_tracing_disabled
from dotenv import load_dotenv
from openai import AsyncOpenAI


def load_config() -> None:
    # 相对于代码加载配置，从其他工作目录启动也有效。
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    set_tracing_disabled(True)


@asynccontextmanager
async def configured_model():
    load_config()
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or key == "your-api-key":
        raise ValueError("请在 .env 中设置自己的 OPENAI_API_KEY（参考 .env.example）。")
    async with AsyncOpenAI(
        api_key=key,
        base_url=os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        timeout=60.0,
        max_retries=2,
    ) as client:
        yield OpenAIChatCompletionsModel(
            model=os.getenv("OPENAI_MODEL", "qwen-max"), openai_client=client
        )
