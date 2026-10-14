import os
import sys
import asyncio
import json
from pathlib import Path

# 百炼模型配置（兼容 OpenAI 规范）
# https://bailian.console.aliyun.com/?tab=model#/api-key
os.environ["OPENAI_API_KEY"] = "sk-337f7e76c80047e6b4b29bbe4a3b364a"
os.environ["OPENAI_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"

from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel
from agents.mcp.server import MCPServerStdio, MCPServerSse
from agents import set_default_openai_api, set_tracing_disabled

# 新版 openai SDK(>=3)用 httpx2，旧版用 httpx，这里做兼容
try:
    from openai import DefaultAsyncHttpx2Client as DefaultAsyncHttpClient
except ImportError:
    from openai import DefaultAsyncHttpxClient as DefaultAsyncHttpClient

set_default_openai_api("chat_completions")
set_tracing_disabled(True)

CURRENT_DIR = Path(__file__).resolve().parent


async def log_request(request):
    print("\n=== HTTP REQUEST ===")
    print(request.method, request.url)
    # 只打印 body，不打印 headers，避免泄露 Authorization
    body = request.content.decode("utf-8")
    try:
        print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(body)


async def log_response(response):
    await response.aread()  # response hook 触发时 body 还没读，需要先读
    print("\n=== HTTP RESPONSE ===")
    print("status:", response.status_code)
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(response.text)



async def test_agent_with_servers(stdio_server: MCPServerStdio, sse_server: MCPServerSse):
    """
    配置 Agent 同时接入 Stdio Server 和 SSE/HTTP Server 两个 MCP 服务源
    """
    # 添加日志
    client_kwargs = {}
    client_kwargs["event_hooks"] = {"request": [log_request], "response": [log_response]}
    http_client = DefaultAsyncHttpClient(**client_kwargs)

    external_client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
        http_client=http_client,
    )

    # mcp.resource 的用法（并不会自动拼接到系统提示词中）
    support_cities_res = await sse_server.read_resource("data://cities")
    cities = support_cities_res.contents[0].text

    # 创建兼容 OpenAI 规范的 Agent，传入两个 MCP Server
    agent = Agent(
        name="MultiMCP-Assistant",
        instructions=(
            "你是一个专业、严谨的智能助理。请根据用户的问题，主动选择并调用合适的工具进行回答；对于复杂任务，可分步骤组合调用多个工具。"
            f"当前天气系统仅支持以下城市查询：{cities}。"
        ),
        mcp_servers=[stdio_server, sse_server],  # 同时注册 stdio 与 http 两个服务器
        model=OpenAIChatCompletionsModel(
            model="qwen3.8-flash",
            openai_client=external_client,
        ),
    )

    # 测试用例列表，覆盖 stdio 工具、http 工具以及跨工具组合
    test_queries = [
        # 测试 1: 触发 stdio 服务的数学计算工具
        # "请帮我计算一下 (128 * 45) + (350 / 7) 的精确数值。",
        # 测试 2: 触发 http 服务的当前时间和城市天气工具
        "请问现在是几月几日几点？另外查询一下北京今天的天气和出行建议。",
        # 测试 3: 跨服务综合调用（同时需要 stdio 的系统信息 + http 的天气）
        # "请查看一下当前主机的操作系统和Python版本，并且告诉我今天上海的天气？",
    ]

    for idx, query in enumerate(test_queries, 1):
        print("\n" + "=" * 60)
        print(f"【测试用例 {idx}】用户提问: {query}")
        print("-" * 60)
        result = await Runner.run(starting_agent=agent, input=query)
        print(f"【Agent 回答】:\n{result.final_output}")


async def main():
    # 1. 配置本地 stdio 方式的 MCP 服务（子进程通信，无需网络端口）
    server_stdio_script = str(CURRENT_DIR / "server_stdio.py")
    stdio_server = MCPServerStdio(
        name="Local-Stdio-Server",
        params={
            "command": sys.executable,
            "args": [server_stdio_script],
            "cwd": str(CURRENT_DIR),
        },
    )

    # 2. 配置本地 HTTP / SSE 方式的 MCP 服务（连接本地 8000 端口）
    # 注意：需要提前启动 server_http.py (python server_http.py)
    sse_server = MCPServerSse(
        name="Local-HTTP-Server",
        params={
            "url": "http://127.0.0.1:8000/sse",
        },
    )

    # 3. 异步上下文管理器中启动并连接两个服务
    print("正在连接 stdio 服务与 http(8000) 服务...")
    async with stdio_server as stdio_conn, sse_server as sse_conn:
        print("两个 MCP 服务连接成功！开始运行 Agent 交互测试...\n")
        await test_agent_with_servers(stdio_conn, sse_conn)


if __name__ == "__main__":
    asyncio.run(main())
