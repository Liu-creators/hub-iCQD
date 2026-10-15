"""基于 OpenAI Agents 框架调用自定义 MCP 工具的 Agent。

通过 SSE（HTTP + SSE）连接 mcp_server.py，把 3 个 MCP 工具
（get_current_time / calculate / text_stats）暴露给 Agent，由模型自主选择调用。

若 MCP server 尚未启动，本脚本会自动在后台拉起 mcp_server.py（默认
http://127.0.0.1:8001/sse），跑完后自动回收；也可以在另一个终端手动先启动
    python mcp_server.py
再运行本脚本（此时不会重复拉起）。

用法：
    python agent_main.py "帮我算 (1234+5678)*2，再告诉我现在北京时间，最后统计 'hello world, welcome to MCP' 有几个单词"
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI

from agents import (
    Agent,
    Runner,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)
from agents.mcp.server import MCPServerSse

# —— DeepSeek（OpenAI 兼容）默认配置 ——
OPENAI_BASE_URL = "https://api.deepseek.com"
OPENAI_MODEL = "deepseek-chat"

# —— MCP 服务地址（SSE）——
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8001/sse")
SERVER_SCRIPT = Path(__file__).with_name("mcp_server.py")

INSTRUCTIONS = """你是一个工具调用助手。你可以调用以下三个 MCP 工具完成任务：

1. get_current_time —— 获取指定时区的当前时间
2. calculate       —— 安全计算四则运算表达式
3. text_stats      —— 统计文本的字符数 / 单词数 / 行数

根据用户需求，按需调用这些工具，并用中文清晰汇总结果。
"""


def _mcp_http_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """构造 MCP 的 HTTP 客户端。

    ``trust_env=False`` 让它忽略系统代理——本机 127.0.0.1:7892 的 Clash 代理会把
    连到 127.0.0.1 的请求也转走，从而返回 502 Bad Gateway。
    """
    return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth, trust_env=False)


def _server_reachable(url: str) -> bool:
    """用 TCP 连接探测 server 是否已监听（原生 socket 不走 HTTP 代理）。"""
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


async def main() -> None:
    user_input = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else None
    if not user_input:
        user_input = input("请输入你的需求：").strip()
    if not user_input:
        print("输入不能为空")
        sys.exit(1)
    if not os.environ.get("OPENAI_API_KEY"):
        print("请先设置环境变量 OPENAI_API_KEY（DeepSeek API Key）")
        sys.exit(1)

    client = AsyncOpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", OPENAI_BASE_URL),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    set_default_openai_client(client, use_for_tracing=False)
    set_default_openai_api("chat_completions")
    set_tracing_disabled(True)

    # 若 MCP server 未运行，自动在后台拉起，跑完自动回收
    auto_proc: subprocess.Popen | None = None
    if not _server_reachable(MCP_SERVER_URL):
        print(f"未检测到 MCP server，自动启动：{SERVER_SCRIPT} …")
        auto_proc = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            if _server_reachable(MCP_SERVER_URL):
                break
            time.sleep(0.3)
        else:
            raise RuntimeError(f"MCP server 在 15s 内未就绪：{MCP_SERVER_URL}")

    server = MCPServerSse(
        name="我的工具集",
        params={
            "url": MCP_SERVER_URL,
            "httpx_client_factory": _mcp_http_client_factory,
        },
    )

    try:
        async with server:
            agent = Agent(
                name="MCP 工具助手",
                instructions=INSTRUCTIONS,
                mcp_servers=[server],
                model=os.environ.get("OPENAI_MODEL", OPENAI_MODEL),
            )
            result = await Runner.run(agent, user_input)
            print(result.final_output)
    finally:
        if auto_proc is not None:
            auto_proc.terminate()
            auto_proc.wait()


if __name__ == "__main__":
    asyncio.run(main())
