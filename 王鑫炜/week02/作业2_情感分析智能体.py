import os
import argparse
import json

from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from openai import APIConnectionError, AuthenticationError
from pydantic import BaseModel, ConfigDict, Field

ENV_PATH = Path(__file__).resolve().parent / "llm.deepseek.env"


class PersonRelation(BaseModel):
    """人物关系图谱中的一条有向边。"""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, description="关系的主体")
    relation: str = Field(min_length=1, description="关系的类型")
    target: str = Field(min_length=1, description="关系的客体")

class RelationGraph(BaseModel):
    """关系列表，JSON Mode 使用对象作为最外层，便于模型稳定返回"""

    model_config = ConfigDict(extra="forbid")

    relations: list[PersonRelation]

SYSTEM_PROMPT = """
角色：
你是人物关系分析智能体。请从用户文本中抽取明确表达的人物情感关系，
并且只返回合法 JSON，不要返回 Markdown 或解释文字。
规则：
1. 每条关系包含 source、relation、target 三个字段。
2. 关系有方向，例如“小明喜欢小姚”表示 source=小明、target=小姚。
3. 将“喜欢、暗恋、倾慕、爱上”等正向爱情情感统一规范为“爱慕”。
4. 其他关系同理，使用简短中文词，例如“讨厌”“感激”“嫉妒”“信任”。
5. 抽取文本中所有明确关系；不猜测、不补充隐含关系、不输出重复关系。
6. 如果没有明确关系，返回空数组。
JSON 格式必须参考以下示例：
{
  "relations": [
    {"source": "人物A", "relation": "爱慕", "target": "人物B"}
  ]
}
""".strip()

class EmotionRelationAgent:
    """基于 OpenAI 兼容接口和 JSON Mode 的关系抽取智能体。"""
    def __init__(self):
        load_dotenv(dotenv_path=ENV_PATH)
        self.model = os.getenv("LLM_MODEL")
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")

        if not api_key or not base_url or not self.model:
            raise RuntimeError("请确保环境变量 LLM_API_KEY、LLM_BASE_URL 和 LLM_MODEL 已正确设置。")
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
    
    def analyze(self, text: str) -> RelationGraph:
        if not text.strip():
            raise ValueError("输入文本不能为空。")
        try:
            response=self.client.chat.completions.create(
                model=self.model,
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
                max_tokens=1000,
                temperature=0.0
            )
        except (APIConnectionError, AuthenticationError) as e:
            raise RuntimeError(f"调用 LLM 接口失败: {e}")
        content = response.choices[0].message.content or ""
        return RelationGraph.model_validate_json(content)

def main() -> None:
    parser = argparse.ArgumentParser(description="人物关系抽取智能体")
    parser.add_argument("text", nargs="?", type=str, help="输入文本（不填写时进入交互输入）")
    args = parser.parse_args()

    text = args.text
    if text is None:
        text = input("请输入需要分析的人物关系文本：").strip()

    agent = EmotionRelationAgent()
    try:
        relation_graph = agent.analyze(text)

        result = [
            relation.model_dump()
            for relation in relation_graph.relations
        ]

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=4
            )
        )
    except Exception as e:
        print(f"分析失败: {e}")

if __name__ == "__main__":
    main()
        
