"""OpenAI Agents SDK Client：通过 MCP 使用天气、成语和翻译工具。"""

import asyncio
import os

import httpx
from agents import (
    Agent,
    AsyncOpenAI,
    OpenAIChatCompletionsModel,
    Runner,
    set_default_openai_api,
    set_tracing_disabled,
)
from agents.mcp.server import MCPServerSse


os.environ["OPENAI_API_KEY"] = "sk-bf4240833btopabue6b33dacd6be11"
os.environ["OPENAI_BASE_URL"] =  "https://api.deepseek.com"
set_default_openai_api("chat_completions")
set_tracing_disabled(True)


def create_local_mcp_http_client(headers=None, timeout=None, auth=None):
    """创建本机 MCP 专用 HTTP 客户端，避免读取 IDE/系统代理设置。"""
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=True,
        trust_env=False,
    )


async def main():
    # 连接已启动的 FastMCP SSE Server；退出 async with 时会关闭连接。
    async with MCPServerSse(
        name="Study Tools MCP Server",
        params={
            "url": "http://127.0.0.1:8000/sse",
            "httpx_client_factory": create_local_mcp_http_client,
        },
    ) as mcp_server:
        external_client = AsyncOpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ["OPENAI_BASE_URL"],
        )

        agent = Agent(
            name="Study Assistant",
            model=OpenAIChatCompletionsModel(
                model="deepseek-flash",
                openai_client=external_client,
            ),
            instructions="""
你是一个学习助手，可以使用 MCP Server 提供的工具。
- 用户询问某个城市今天的天气时，调用 get_today_weather，并把城市名作为 city 参数。
- 用户询问成语含义或例句时，调用 explain_idiom，并把成语作为 idiom 参数。
- 用户要求把英文翻译成中文时，调用 translate_english_to_chinese，并把原文作为 text 参数。
遇到以上三类请求必须先调用对应工具，再根据工具返回的内容回答；不要编造天气、成语词典结果或译文。
            """.strip(),
            mcp_servers=[mcp_server],
        )

        print("  查一下北京今天的天气")
        print("  请解释成语‘守株待兔’")
        print("  把这句话翻译成中文：The early bird catches the worm.")
        print("输入 q 或 exit 退出。")

        while True:
            message = input("\n你：").strip()
            if message.lower() in {"q", "quit", "exit", "退出"}:
                break
            if not message:
                continue

            result = await Runner.run(starting_agent=agent, input=message)
            print(f"助手：{result.final_output}")


if __name__ == "__main__":
    asyncio.run(main())
