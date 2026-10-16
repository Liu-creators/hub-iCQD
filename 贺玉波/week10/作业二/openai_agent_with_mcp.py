import os

os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com/"
os.environ["OPENAI_API_KEY"] = ""

import asyncio
from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel
from agents.mcp import MCPServer
from agents.mcp.server import MCPServerSse
from agents import set_default_openai_api, set_tracing_disabled
set_default_openai_api("chat_completions")
set_tracing_disabled(True)


async def run_agent(mcp_server: MCPServer) -> None:
	external_client = AsyncOpenAI(
		api_key=os.environ["OPENAI_API_KEY"],
		base_url=os.environ["OPENAI_BASE_URL"],
	)

	agent = Agent(
		name="课程助手",
		instructions=(
			"你是课程学习助手。需要查询时间、进行计算或搜索课程时，"
			"必须优先调用对应的 MCP 工具，并根据工具结果回答。"
		),
		mcp_servers=[mcp_server],
		model=OpenAIChatCompletionsModel(
			model="deepseek-chat",
			openai_client=external_client,
		),
	)

	questions = [
		"现在几点？",
		"请计算 (12 + 8) * 3 / 2。",
		"请搜索和 Agent 相关的课程。",
	]
	for question in questions:
		print(f"\n用户：{question}")
		result = await Runner.run(starting_agent=agent, input=question)
		print(f"助手：{result.final_output}")


async def main() -> None:
	async with MCPServerSse(
		name="课程工具 MCP 服务",
		params={"url": "http://localhost:8000/sse"},
	) as server:
		await run_agent(server)


if __name__ == "__main__":
	asyncio.run(main())