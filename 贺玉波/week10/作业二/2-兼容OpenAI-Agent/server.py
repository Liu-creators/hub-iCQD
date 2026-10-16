import random
import ast
import operator
from datetime import datetime
from fastmcp import FastMCP
from typing import Union
mcp = FastMCP(name="Dice Roller")

# 工具名字、传入参数类型、返回值类型、函数的注释（工具说明）

@mcp.tool
def roll_dice(n_dice: int) -> list[int]:
    """Roll `n_dice` 6-sided dice and return the results."""
    return [random.randint(10, 60) for _ in range(n_dice)]

@mcp.tool
def get_news() -> Union[int, str]:
    """Get latest news."""
    return "最新消息 Qwen4 is coming!"


@mcp.tool
def get_current_time() -> str:
    """Get the current local date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@mcp.tool
def calculate(expression: str) -> Union[float, str]:
    """Safely calculate an arithmetic expression containing numbers and + - * / ( )."""
    operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
    }

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            return operators[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in operators:
            return operators[type(node.op)](evaluate(node.operand))
        raise ValueError("只支持数字和 +、-、*、/、括号运算")

    try:
        tree = ast.parse(expression, mode="eval")
        return evaluate(tree.body)
    except (SyntaxError, ValueError, ZeroDivisionError) as exc:
        return f"计算失败：{exc}"


@mcp.tool
def search_course(keyword: str) -> list[str]:
    """Search the course catalog by keyword and return matching course names."""
    courses = [
        "大模型基础",
        "Transformer 和 BERT",
        "RAG 工程化实现",
        "Agent 开发与 VibeCoding",
        "MCP 应用开发",
    ]
    return [course for course in courses if keyword.lower() in course.lower()]


if __name__ == "__main__":
    mcp.run(transport="sse", port=8000)