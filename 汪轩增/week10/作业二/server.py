"""MCP Server：提供天气查询、成语解释、英译中三个工具。"""

import json
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastmcp import FastMCP


mcp = FastMCP(name="Study Tools")


def _get_json(url: str) -> dict:
    """使用 Python 标准库请求 HTTP JSON 接口。"""
    request = Request(url, headers={"User-Agent": "Week10-MCP-Study-Tools/1.0"})
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


@mcp.tool
def get_today_weather(city: str) -> str:
    """查询指定城市今天的天气、气温、湿度和风速。参数 city 为城市名称，如北京、上海。"""
    city = city.strip()
    if not city:
        return "请提供要查询的城市名称。"

    # 第一步：将城市名转换为经纬度。
    geo_query = urlencode({"name": city, "count": 1, "language": "zh", "format": "json"})
    try:
        geo_data = _get_json(f"https://geocoding-api.open-meteo.com/v1/search?{geo_query}")
        locations = geo_data.get("results") or []
        if not locations:
            return f"没有查到“{city}”这个地点，请检查城市名称后重试。"

        location = locations[0]
        latitude = location["latitude"]
        longitude = location["longitude"]
        timezone = location.get("timezone", "auto")

        # 第二步：按经纬度查询当地当前天气和今日预报。
        weather_query = urlencode({
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": timezone,
            "forecast_days": 1,
        })
        weather = _get_json(f"https://api.open-meteo.com/v1/forecast?{weather_query}")
    except (URLError, TimeoutError, KeyError, ValueError) as error:
        return f"天气服务暂时不可用：{error}"

    current = weather.get("current", {})
    daily = weather.get("daily", {})
    weather_code = current.get("weather_code", daily.get("weather_code", [None])[0])
    descriptions = {
        0: "晴", 1: "大致晴朗", 2: "局部多云", 3: "阴",
        45: "有雾", 48: "雾凇",
        51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "强冻毛毛雨",
        61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
        71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
        80: "小阵雨", 81: "中阵雨", 82: "强阵雨", 85: "小阵雪", 86: "强阵雪",
        95: "雷雨", 96: "雷雨伴小冰雹", 99: "雷雨伴大冰雹",
    }
    description = descriptions.get(weather_code, "天气状况未知")
    city_name = location.get("name", city)
    country = location.get("country", "")
    place = f"{country}{city_name}" if country else city_name
    date = (daily.get("time") or ["今天"])[0]
    temp = current.get("temperature_2m", "未知")
    feels_like = current.get("apparent_temperature", "未知")
    humidity = current.get("relative_humidity_2m", "未知")
    wind = current.get("wind_speed_10m", "未知")
    high = (daily.get("temperature_2m_max") or ["未知"])[0]
    low = (daily.get("temperature_2m_min") or ["未知"])[0]
    rain_chance = (daily.get("precipitation_probability_max") or ["未知"])[0]

    return (
        f"{place}（{date}）天气：{description}；当前气温 {temp}°C，体感 {feels_like}°C，"
        f"湿度 {humidity}%，风速 {wind} km/h；今日最高 {high}°C、最低 {low}°C，"
        f"最高降水概率 {rain_chance}%。数据来源：Open-Meteo。"
    )


_IDIOM_GUIDE = {
    "守株待兔": "比喻不主动努力，而抱着侥幸心理，希望得到意外收获。例：学习不能守株待兔，要主动复习。",
    "画蛇添足": "比喻做了多余的事，反而不恰当。例：这段说明已经很清楚，再加一段反而画蛇添足。",
    "亡羊补牢": "羊丢失后修补羊圈，比喻出了问题后及时补救，仍然来得及。例：发现错误后马上改正，也算亡羊补牢。",
    "井底之蛙": "比喻见识狭窄、眼界有限的人。例：多读书、多旅行，才能避免做井底之蛙。",
    "刻舟求剑": "比喻拘泥、不知根据情况变化而改变做法。例：市场已经变化，还照旧方案执行，就是刻舟求剑。",
    "掩耳盗铃": "比喻自己欺骗自己，以为掩盖事实就能解决问题。例：不检查错误只删掉提示，是掩耳盗铃。",
    "一举两得": "做一件事同时得到两方面的好处。例：骑车上班既锻炼身体又节省时间，真是一举两得。",
    "半途而废": "事情没有完成就停止。例：学语言要坚持，不能半途而废。",
}


@mcp.tool
def explain_idiom(idiom: str) -> str:
    """解释常见中文成语，给出含义和例句。参数 idiom 为要解释的成语。"""
    idiom = idiom.strip()
    if not idiom:
        return "请提供要解释的成语。"
    explanation = _IDIOM_GUIDE.get(idiom)
    if explanation:
        return f"{idiom}：{explanation}"
    known_idioms = "、".join(_IDIOM_GUIDE)
    return f"当前内置示例词库暂未收录“{idiom}”。可查询的成语有：{known_idioms}。"


@mcp.tool
def translate_english_to_chinese(text: str) -> str:
    """将英文文本翻译成简体中文。参数 text 为需要翻译的英文文本。"""
    text = text.strip()
    if not text:
        return "请提供需要翻译的英文文本。"

    # 使用 MyMemory 公共翻译接口演示在线翻译；该接口可能有用量限制。
    query = urlencode({"q": text, "langpair": "en|zh-CN"})
    try:
        data = _get_json(f"https://api.mymemory.translated.net/get?{query}")
        translated = data.get("responseData", {}).get("translatedText")
        if not translated:
            return "翻译服务没有返回译文，请稍后重试。"
        return translated
    except (URLError, TimeoutError, ValueError) as error:
        return f"翻译服务暂时不可用：{error}"


if __name__ == "__main__":
    # 本作业沿用课程示例的 SSE 传输方式，Client 连接地址为 http://localhost:8000/sse。
    mcp.run(transport="sse", port=8000)
