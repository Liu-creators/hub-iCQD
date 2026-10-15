"""自定义 MCP 工具集（3 个工具，纯标准库实现，无需网络/API key）。

工具列表：
    1. get_current_time —— 获取指定时区的当前时间
    2. calculate       —— 安全计算四则运算表达式
    3. text_stats      —— 统计文本的字符数 / 单词数 / 行数

以 SSE（HTTP + SSE）方式启动（默认监听 http://127.0.0.1:8001/sse），供 openai-agents 的
MCPServerSse 调用：
    python mcp_server.py
"""
from __future__ import annotations

import ast
import operator
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

MCP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("MCP_PORT", "8001"))

mcp = FastMCP("我的工具集", host=MCP_HOST, port=MCP_PORT)


@mcp.tool()
def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """获取指定时区的当前日期和时间。

    Args:
        timezone: IANA 时区名（如 Asia/Shanghai、America/New_York），默认 Asia/Shanghai。
    """
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
        timezone = "Asia/Shanghai"
    now = datetime.now(tz)
    return now.strftime(f"{timezone} 当前时间：%Y-%m-%d %H:%M:%S")


# 白名单：只允许二元 + - * / 与一元 + -
_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval(node: ast.AST) -> float:
    """基于 AST 白名单递归求值，杜绝 eval 注入。"""
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    raise ValueError(f"不支持的表达式内容: {type(node).__name__}")


@mcp.tool()
def calculate(expression: str) -> float:
    """安全计算四则运算表达式（仅支持 + - * /、括号、整数和小数）。

    Args:
        expression: 数学表达式，如 "(12 + 34) * 2"。
    """
    tree = ast.parse(expression, mode="eval")
    return _eval(tree)


@mcp.tool()
def text_stats(text: str) -> dict:
    """统计文本的字符数、单词数和行数。

    Args:
        text: 要统计的文本。
    """
    words = text.split()
    return {
        "字符数": len(text),
        "单词数": len(words),
        "行数": text.count("\n") + (1 if text else 0),
    }


if __name__ == "__main__":
    mcp.run(transport="sse")
