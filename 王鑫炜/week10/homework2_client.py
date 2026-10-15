"""作业二客户端：由 Agent 选择并调用 MCP 工具，展示实际调用记录。"""
import argparse
import asyncio
import os
import sys

from agents import Agent, Runner
from agents.mcp import MCPServerSse

from config import configured_model, load_config

DEMO_QUERIES = [
    "请调用工具精确计算 0.1 加 0.2。",
    "请调用工具计算从 2026-10-01 到 2026-10-15 相隔多少天。",
    "请调用工具统计这段文本：你好，MCP! Hello world",
]


async def run_query(server, model, query: str):
    agent = Agent(
        name="MCPAssistant",
        instructions="你是工具助手。对于计算、日期间隔、文本统计、骰子和演示新闻问题，"
                     "必须调用相应 MCP 工具，不能心算或伪造工具结果。用中文总结真实工具结果。"
                     "工具报错时说明原因，不得编造答案。演示新闻不是实时新闻。",
        model=model, mcp_servers=[server],
    )
    return await Runner.run(agent, input=query, max_turns=8)


def print_run(result) -> None:
    for item in result.new_items:
        if item.type == "tool_call_item":
            raw = item.raw_item
            print(f"[调用工具] {raw.name}，参数：{raw.arguments}")
        elif item.type == "tool_call_output_item":
            print(f"[工具返回] {item.output}")
    print(f"[最终回答] {result.final_output}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", help="自定义问题；省略则依次演示三个新增工具")
    parser.add_argument("--url", help="覆盖 MCP_SERVER_URL")
    args = parser.parse_args()
    load_config()
    url = args.url or os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/sse")
    async with configured_model() as model:
        async with MCPServerSse(name="Week10Tools", params={"url": url}, cache_tools_list=True) as server:
            print("[可用工具] " + ", ".join(tool.name for tool in await server.list_tools()))
            for query in [args.query] if args.query is not None else DEMO_QUERIES:
                if not query.strip():
                    raise ValueError("问题不能为空")
                print(f"\n[用户问题] {query}")
                print_run(await run_query(server, model, query))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        detail = str(exc) if isinstance(exc, ValueError) else "请确认服务端已启动，且模型配置、网络正常。"
        print(f"调用失败（{type(exc).__name__}）：{detail}", file=sys.stderr)
        sys.exit(1)
