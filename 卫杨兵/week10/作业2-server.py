import random
from fastmcp import FastMCP
from typing import Union
from datetime import datetime

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


# 新增工具1
@mcp.tool
def get_weather(city: str) -> str:
    """查询指定城市的天气情况。

    city: 城市名称，例如 "北京"、"上海"
    """
    weather_map = {
        "北京": "晴，气温 22°C，空气质量良好",
        "上海": "多云，气温 26°C，有轻微雾霾",
        "广州": "雷阵雨，气温 30°C，湿度较高",
        "深圳": "阴天，气温 28°C，微风",
    }
    return weather_map.get(city, f"{city}：暂无该城市的天气数据")


# 新增工具2
@mcp.tool
def calculate(expression: str) -> Union[float, str]:
    """计算一个数学表达式并返回结果。支持加减乘除和括号，例如 "3 * (4 + 5)"。

    expression: 待计算的数学表达式字符串
    """
    try:
        # 限制可用字符，避免安全问题
        allowed = set("0123456789+-*/(). ")
        if not set(expression).issubset(allowed):
            return "错误：表达式包含非法字符"
        result = eval(expression, {"__builtins__": {}}, {})
        return float(result)
    except Exception as e:
        return f"计算失败：{e}"


# 新增工具3
@mcp.tool
def get_current_time(timezone: str = "local") -> str:
    """获取当前时间。

    timezone: 时区标识，默认 "local" 表示本地时间
    """
    now = datetime.now()
    return now.strftime(f"[{timezone}] %Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    mcp.run(transport="sse", port=8000)
