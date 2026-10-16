"""作业二服务端：沿用课堂 SSE，保留两个示例工具并新增三个工具。"""
import argparse
import random
import re
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from fastmcp import FastMCP

mcp = FastMCP(name="Week10Tools")


@mcp.tool
def roll_dice(n_dice: int) -> list[int]:
    """Roll 1 to 100 standard six-sided dice and return their values."""
    if not 1 <= n_dice <= 100:
        raise ValueError("骰子数量必须在 1 到 100 之间")
    # 修正课堂示例 randint(10, 60) 与六面骰子描述不一致的问题。
    return [random.randint(1, 6) for _ in range(n_dice)]


@mcp.tool
def get_news() -> str:
    """Return a static classroom demo message, NOT real-time news."""
    return "【静态演示数据，非实时新闻】第10周课程学习 Agent 框架和 MCP 工具调用。"


@mcp.tool
def calculate(a: str, operator: Literal["+", "-", "*", "/"], b: str) -> dict:
    """Calculate two decimal numbers. Pass operands as strings; supports +, -, *, /."""
    # 限定输入为普通十进制数，不执行任意表达式或代码。
    for value in (a, b):
        if len(value) > 50 or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value, flags=re.ASCII):
            raise ValueError("操作数必须为不超过50字符的普通十进制数")
    left, right = Decimal(a), Decimal(b)
    if operator == "/" and right == 0:
        raise ValueError("除数不能为零")
    with localcontext() as context:
        context.prec = 110  # 容纳两个最多50字符操作数的加减乘；除法可能舍入。
        if operator == "+":
            result = left + right
        elif operator == "-":
            result = left - right
        elif operator == "*":
            result = left * right
        elif operator == "/":
            result = left / right
        else:
            raise ValueError("不支持的运算符")
    return {"a": a, "operator": operator, "b": b, "result": format(result, "f")}


@mcp.tool
def date_difference(start_date: str, end_date: str) -> dict:
    """Return signed calendar days from start_date to end_date, both YYYY-MM-DD. Same date = 0."""
    for value in (start_date, end_date):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value, flags=re.ASCII):
            raise ValueError("日期格式必须为 YYYY-MM-DD")
    days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days
    return {"start_date": start_date, "end_date": end_date, "days": days}


@mcp.tool
def text_statistics(text: str) -> dict:
    """Count Unicode code points, non-whitespace characters, basic CJK characters and English words."""
    if len(text) > 10000:
        raise ValueError("文本不能超过10000个字符")
    return {
        "characters": len(text),
        "non_whitespace": sum(not ch.isspace() for ch in text),
        "chinese_characters": len(re.findall(r"[\u4e00-\u9fff]", text)),
        "english_words": len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)*", text)),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    mcp.run(transport="sse", host="127.0.0.1", port=args.port)
