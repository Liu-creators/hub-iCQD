import os
import platform
import sys
from fastmcp import FastMCP

# 初始化 stdio 协议的 MCP 服务
mcp = FastMCP(name="Local-System-Tools")


@mcp.tool
def calculate(expression: str) -> str:
    """计算数学表达式的结果。支持基础四则运算、幂运算等常见数学表达式。
    
    Args:
        expression: 待计算的数学表达式，例如: '128 * 45 + 350 / 7' 或 '2 ** 10'
    """
    try:
        # 允许的基础数学函数和安全命名空间
        allowed_names = {
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "pow": pow,
        }
        # 安全计算：禁止内置危险函数
        result = eval(expression, {"__builtins__": None}, allowed_names)
        return f"计算结果: {result}"
    except Exception as e:
        return f"计算失败: 表达式错误或不支持 ({str(e)})"


@mcp.tool
def get_system_info() -> dict:
    """获取当前宿主机系统的基础环境信息，包括操作系统、平台架构及 Python 版本。"""
    return {
        "os_name": os.name,
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python_version": sys.version.split()[0],
        "system": platform.system(),
    }


@mcp.tool
def read_local_file(filepath: str) -> str:
    """安全读取本地指定文件的文本内容（默认限制读取大小，防止文件过大）。
    
    Args:
        filepath: 本地文件路径
    """
    if not os.path.exists(filepath):
        return f"错误: 文件 '{filepath}' 不存在。"
    
    if os.path.isdir(filepath):
        return f"错误: 路径 '{filepath}' 是一个目录，非文本文件。"

    try:
        # 限制读取前 4000 个字符
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(4000)
            return content
    except Exception as e:
        return f"读取文件失败: {str(e)}"


if __name__ == "__main__":
    # 使用 stdio 方式运行（通过标准输入输出与客户端通信）
    mcp.run(transport="stdio")
