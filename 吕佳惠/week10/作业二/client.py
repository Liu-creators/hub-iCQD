import os

os.environ["OPENAI_API_KEY"] = "sk-xx"
os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"

from agents.mcp.server import MCPServerSse
import asyncio
from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel
from agents.mcp import MCPServer
from agents import set_default_openai_api, set_tracing_disabled
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

async def run(mcp_server: MCPServer):
    external_client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )

    # openai agent
    agent = Agent(
        name="Assistant",
        instructions="",
        mcp_servers=[mcp_server], # tools
        model=OpenAIChatCompletionsModel(
            model="deepseek-flash",
            openai_client=external_client,
        )
    )

    # list tool -> select tool -> execute tool -> return result -> gpt answer
    # list tool 得到 可选api 参数
    # select tool 本质就是function call

    # 人传入tool，function call execute tool
    message = "最近有什么新闻？"
    print(f"Running: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)
    # 等同于：工具选择、工具调用、工具回答的总结

    """
    step1，通过mcp client mcp list tool，得到mcp server 可选的工具、工具的参数、返回格式
    step2， 工具、工具的参数、返回格式 汇总为tools / functioncall 的格式 通过大模型 选择一个工具 -》 传入参数
    step3, 通过mcp client 调用execute tool 在mcp server 执行这个工具 -》 返回结果
    step4， 返回结果汇总在提示词，调用大模型得到结果
    """


    # tool 11 17 13
    message = "摇3次骰子得到结果。"
    print(f"Running: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)

# ====== 新增3个工具的测试提问 ======
    message = "矩形长5，宽3，面积是多少？"
    print(f"\nRunning: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)

    message = "统计这句话的字符数量：人工智能Agent结合MCP工具非常有趣！"
    print(f"\nRunning: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)

    message = "25摄氏度等于多少华氏度？"
    print(f"\nRunning: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)
    
async def main():
    async with MCPServerSse(
            name="SSE Python Server",
            params={
                "url": "http://localhost:8000/sse", # mcp server 通过http 方式沟通
            },
    )as server:
        await run(server)

if __name__ == "__main__":
    asyncio.run(main())
