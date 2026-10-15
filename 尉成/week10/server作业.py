import random
from fastmcp import FastMCP
from typing import Union, Annotated
from pydantic import Field
from datetime import datetime
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP(name="Dice Roller")

# 工具名字、传入参数类型、返回值类型、函数的注释（工具说明）

@mcp.tool
def roll_dice(
    n_dice: Annotated[int, Field(ge=1, le=100, description="骰子数量")] = 1,
) -> list[int]:
    """Roll `n_dice` 6-sided dice (each 1-6) and return the results.

    Args:
        n_dice: 骰子数量，范围 1~100。
    """
    if not 1 <= n_dice <= 100:
        raise ValueError("n_dice must be between 1 and 100")
    return [random.randint(1, 6) for _ in range(n_dice)]

@mcp.tool
def get_news() -> str:
    """Get the latest AI news headline."""
    try:
        # 真实实现：requests.get(...)
        return "最新消息：Qwen4 is coming!"
    except Exception as e:
        logger.exception("get_news failed")
        raise RuntimeError(f"获取新闻失败: {e}") from e

@mcp.tool
def echo(
    text: Annotated[str, Field(description="要回显的文本")],
    times: Annotated[int, Field(ge=1, le=10, description="重复次数，1~10")] = 1,
) -> dict:
    """回显输入文本，并附带服务端时间戳。

    用于验证：字符串参数、整数参数、默认值、字典返回值是否都能正确往返。
    """
    return {
        "received": text,
        "times": times,
        "echoed": (text + " ") * times,
        "server_time": datetime.now().isoformat(),
    }

@mcp.tool
def diagnose(
    mode: Annotated[str, Field(description="测试模式：ok / fail / slow")] = "ok",
) -> str:
    """诊断工具：按 mode 返回正常结果、抛异常、或延迟响应。

    用于验证：异常是否能正确回传给 LLM，让它自己决定重试或换工具；
    以及慢响应时事件循环是否仍能正常工作。
    """
    import time

    if mode == "ok":
        return "诊断正常：Server 工作良好"

    if mode == "fail":
        raise RuntimeError("模拟故障：这是 diagnose 工具故意抛出的异常")

    if mode == "slow":
        time.sleep(3)   # 故意阻塞 3 秒
        return "慢响应完成：等待了 3 秒"

    raise ValueError(f"未知 mode: {mode}，只支持 ok / fail / slow")


@mcp.tool
def list_capabilities() -> dict:
    """返回当前 MCP Server 的能力清单和已注册工具列表。

    用于验证：Server 元信息能否作为工具被 LLM 查询；
    以及嵌套结构（list[dict]）的返回值序列化是否正常。
    """
    import platform
    import sys

    return {
        "server_name": "Dice Roller",
        "python_version": sys.version.split()[0],
        "platform": platform.system(),
        "tools": [
            {"name": "roll_dice", "description": "掷骰子，返回 1~6 的随机数列表"},
            {"name": "get_news", "description": "获取最新新闻标题"},
            {"name": "echo", "description": "回显文本并附带时间戳"},
            {"name": "diagnose", "description": "诊断工具，支持 ok/fail/slow 模式"},
            {"name": "list_capabilities", "description": "列出当前 Server 的能力清单"},
        ],
    }

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)