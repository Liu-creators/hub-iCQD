from datetime import datetime
from zoneinfo import ZoneInfo
from fastmcp import FastMCP

# 初始化基于网络协议的 MCP 服务
mcp = FastMCP(name="Remote-Web-Tools")


@mcp.tool
def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """获取指定时区的当前日期、时间与星期。
    
    Args:
        timezone: 时区名称，例如 'Asia/Shanghai', 'UTC', 'America/New_York'，默认为 'Asia/Shanghai'
    """
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        weekday_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}
        weekday = weekday_map[now.weekday()]
        return f"当前时区: {timezone} | 时间: {now.strftime('%Y-%m-%d %H:%M:%S')} | {weekday}"
    except Exception as e:
        return f"时区解析失败: {str(e)}，请传入有效的 IANA 时区标识（如 'Asia/Shanghai'）"


@mcp.tool
def get_forecast(city: str) -> str:
    """获取 一个城市的 天气"""
    return f"{city} 晴天☀️"

@mcp.resource("data://cities")
def list_cities() -> str:
    """支持的城市列表"""
    return "上海、北京"


if __name__ == "__main__":
    # 使用 SSE / HTTP 方式在 8000 端口启动
    mcp.run(transport="sse", port=8000)
