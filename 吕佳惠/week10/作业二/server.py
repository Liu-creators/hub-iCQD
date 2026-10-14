import random
from fastmcp import FastMCP

mcp = FastMCP(name="Dice Roller")

# 工具名字、传入参数类型、返回值类型、函数的注释（工具说明）

@mcp.tool
def roll_dice(n_dice: int) -> list[int]:
    """Roll `n_dice` 6-sided dice and return the results."""
    return [random.randint(10, 60) for _ in range(n_dice)]

@mcp.tool
def get_news() -> str:
    """Get latest news."""
    return "最新消息 Qwen4 is coming!"

# ========== 新增工具1：计算矩形面积 ==========
@mcp.tool
def calc_area(width: float, height: float) -> float:
    """
    计算矩形面积
    Args:
        width: 矩形宽度
        height: 矩形高度
    Return:
        矩形面积
    """
    return width * height

# ========== 新增工具2：统计文本字符数 ==========
@mcp.tool
def text_count(content: str) -> int:
    """
    统计输入文本的字符总数（包含中文、标点）
    Args:
        content: 需要统计的文本
    Return:
        文本字符数量
    """
    return len(content)

# ========== 新增工具3：摄氏度转华氏度 ==========
@mcp.tool
def convert_temp(celsius: float) -> float:
    """
    摄氏度转换为华氏温度
    Args:
        celsius: 摄氏温度
    Return:
        对应的华氏温度
    """
    return celsius * 9 / 5 + 32

if __name__ == "__main__":
    mcp.run(transport="sse", port=8000)