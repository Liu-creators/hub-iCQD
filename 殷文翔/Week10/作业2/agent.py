from agents import Agent, set_tracing_disabled,Runner
from agents import AsyncOpenAI, OpenAIChatCompletionsModel
from agents.mcp import MCPServerSse
from contextlib import asynccontextmanager

import os
import asyncio

set_tracing_disabled(False)
client = AsyncOpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url=os.getenv("DEEPSEEK_URL"))

@asynccontextmanager
async def get_agent():

    async with MCPServerSse(
        name="my-mcp",
        params={
                "url": "http://localhost:8000/sse"
            }
    ) as mcp:
        agent = Agent(
            name="mcp_agent",
            instructions="你是一个智能助手",
            model=OpenAIChatCompletionsModel(
                model="deepseek-flash",
                openai_client=client
            ),
            mcp_servers=[mcp]
        )

        yield agent

# async def main():
#     async with get_agent() as agent:
#      result = await Runner.run(agent,"你好，你能帮我查询一下广州的天气吗?")
#      print(result.final_output)
#
# asyncio.run(main())