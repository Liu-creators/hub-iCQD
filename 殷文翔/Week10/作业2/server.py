import random
import requests
from typing import Annotated
from datetime import date
import hashlib
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

API_KEY = 'DuU5ITPgxq64UdER5R3KdHradft2sTgb'

@mcp.tool
def get_weather_5day(city:Annotated[str,"city name"]) -> str:
    """Get weather conditions for the next 5 days."""
    params = {'q': city, 'apikey': API_KEY, 'language': 'zh-cn'}
    response = requests.get("https://openapi.weathercn.com/locations/v1/cities/translate", params=params)
    city_key = response.json()[0]["Key"]

    url = f"https://openapi.weathercn.com/forecasts/v1/daily/5day/{city_key}.json"
    params = {'apikey': API_KEY, 'language': 'zh-cn', 'details': 'true'}
    response = requests.get(url, params=params)
    print(response.json()["Headline"]["Text"])
    return f"{city}:{response.json()['Headline']['Text']}"

@mcp.tool()
def fortune_teller(name: str) -> dict:
    """根据名字预测今日运势。同一个人同一天结果固定。"""
    today = date.today().isoformat()
    seed = hashlib.sha256(
        f"{name}:{today}".encode()
    ).digest()
    value = int.from_bytes(seed[:8], "big")

    fortunes = [
        "大吉！今天适合开启新的冒险。",
        "中吉！会遇见意想不到的好消息。",
        "小吉！平凡的一天藏着小惊喜。",
        "末吉！保持耐心，幸运正在靠近。",
        "神秘！今天可能触发隐藏剧情。"
    ]

    return {
        "name": name,
        "date": today,
        "luck_score": value % 100 + 1,
        "fortune": fortunes[value % len(fortunes)],
        "lucky_number": (value // 7) % 99 + 1
    }

@mcp.tool()
def emotion_analyzer(text: str) -> dict:
    """通过中文关键词判断文本情绪，仅用于趣味测试。"""
    keywords = {
        "开心": ["开心", "快乐", "高兴", "幸福", "哈哈"],
        "难过": ["难过", "伤心", "悲伤", "失落", "哭"],
        "愤怒": ["生气", "愤怒", "讨厌", "气死", "烦"],
        "焦虑": ["焦虑", "担心", "紧张", "害怕", "不安"]
    }

    scores = {
        emotion: sum(text.count(word) for word in words)
        for emotion, words in keywords.items()
    }

    best = max(scores, key=scores.get)
    emotion = best if scores[best] > 0 else "平静或未知"

    return {
        "text": text,
        "emotion": emotion,
        "scores": scores,
        "note": "这是关键词演示，不是真正的情绪识别模型"
    }

if __name__ == "__main__":
    mcp.run(transport="sse", port=8000)