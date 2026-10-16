import os
import asyncio
from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel
from agents.mcp import MCPServer
from agents.mcp.server import MCPServerSse
from agents import set_default_openai_api, set_tracing_disabled

set_default_openai_api("chat_completions")
set_tracing_disabled(True)

os.environ["OPENAI_API_KEY"] = "***441deb9b8***5cbbb8"
os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"


async def run(mcp_server: MCPServer):
    external_client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )

    # openai agent
    agent = Agent(
        name="Assistant",
        instructions="",
        mcp_servers=[mcp_server],  # tools
        model=OpenAIChatCompletionsModel(
            model="deepseek-flash",
            openai_client=external_client,
        )
    )

    # 查询天气
    message = "广州天气怎么样？"
    print(f"Running: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)

    # 数学计算
    message = "计算3 * (4 + 5)的结果？"
    print(f"Running: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)

    # 当前时间
    message = "当前时间是多少？"
    print(f"Running: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)


async def main():
    # 定义了远程 mcp server 链接方式
    async with MCPServerSse(
            name="SSE Python Server",
            params={
                "url": "http://localhost:8000/sse",  # mcp server 通过http 方式沟通
            },
    ) as server:
        await run(server)


if __name__ == "__main__":
    asyncio.run(main())
