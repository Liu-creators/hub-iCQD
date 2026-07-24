"""
情感分析智能体 (Sentiment Analysis Agent)

使用 DeepSeek API 的 JSON mode 能力，从中文文本中提取人物关系图谱。
输入一段描述人物关系的文本，输出结构化的关系列表。

输出格式：
[
    {"source": "人物A", "relation": "关系类型", "target": "人物B"},
    ...
]
"""

import json
import os
from typing import Optional

from openai import OpenAI


# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

RELATION_SYSTEM_PROMPT = """你是一个中文情感分析和人物关系抽取专家。
你的任务是从用户输入的文本中，提取所有人物之间的情感关系。

关系类型包括（但不限于）：
- "爱慕"：喜欢、爱、暗恋、追求等正面情感
- "厌恶"：讨厌、恨、反感等负面情感
- "暗恋"：单方面的喜欢但未表达
- "朋友"：朋友关系
- "家人"：亲属关系
- "恋人"：恋爱关系
- "嫉妒"：嫉妒或吃醋
- "同情"：怜悯或同情
- "仇恨"：深层的恨意或敌意
- "信任"：信任或依赖
- "依赖"：依赖或依附
- "崇拜"：崇拜或仰慕

请严格按照以下 JSON 格式输出，不要包含任何其他文字：
[
    {"source": "人物A", "relation": "关系类型", "target": "人物B"},
    {"source": "人物B", "relation": "关系类型", "target": "人物C"}
]

注意：
1. source 和 target 必须是文本中出现的具体人名
2. relation 必须是上述定义的关系类型之一，如不能完全匹配请选择最接近的
3. 如果某个人物有单向情感（如 A 喜欢 B，但 B 不一定喜欢 A），只输出 A→B 的关系
4. 如果文本中没有明确的人物关系，输出空数组 []
"""


class RelationshipExtractor:
    """基于 DeepSeek JSON mode 的人物关系抽取器"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = base_url or DEEPSEEK_BASE_URL
        self.model = model or DEEPSEEK_MODEL
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def extract(self, text: str) -> list[dict]:
        """
        从文本中提取人物关系。

        Args:
            text: 中文描述文本，如 "小明喜欢小姚，但是小姚喜欢小王。"

        Returns:
            关系列表，每个元素包含 source, relation, target
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": RELATION_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=1024,
            )

            content = response.choices[0].message.content
            data = json.loads(content)

            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for key in ("relationships", "relations", "edges", "results", "data"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
                values = [v for v in data.values() if isinstance(v, list)]
                if len(values) == 1:
                    return values[0]
            return []

        except Exception as e:
            raise RuntimeError(f"关系抽取失败: {e}")

    def extract_with_example(self, text: str) -> list[dict]:
        """
        带示例的抽取（few-shot），对复杂文本效果更好。
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": RELATION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": "张三非常喜欢李四，但是李四只在乎王五。",
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            [
                                {"source": "张三", "relation": "爱慕", "target": "李四"},
                                {"source": "李四", "relation": "爱慕", "target": "王五"},
                            ],
                            ensure_ascii=False,
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=1024,
            )

            content = response.choices[0].message.content
            data = json.loads(content)

            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for key in ("relationships", "relations", "edges", "results", "data"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
                values = [v for v in data.values() if isinstance(v, list)]
                if len(values) == 1:
                    return values[0]
            return []

        except Exception as e:
            raise RuntimeError(f"关系抽取失败: {e}")


# 便捷函数
def extract_relationships(text: str) -> list[dict]:
    """快速抽取人物关系（使用默认配置）"""
    extractor = RelationshipExtractor()
    return extractor.extract(text)
