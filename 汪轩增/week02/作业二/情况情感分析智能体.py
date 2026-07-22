import json
import os
from pydantic import BaseModel, Field
from openai import OpenAI


# 1. 定义关系图谱的数据结构
class Relation(BaseModel):
    source: str = Field(description="关系的起点人物")
    relation: str = Field(description="人物之间的情感或关系类型")
    target: str = Field(description="关系的终点人物")

class RelationshipGraph(BaseModel):
    graph: list[Relation]

# 2. 情感与关系分析 Agent
class RelationshipAnalysisAgent:

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-chat",
    ):
        # 统一使用 LLM_API_KEY 或 OPENAI_API_KEY 环境变量
        api_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or "sk-86fec757d81a42b0bf6a8a514d55a9c7"
        )
        base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or "https://api.deepseek.com"
        )

        self.model = model
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    def analyze(self, text: str) -> list[dict]:
        """分析文本并返回结构化数据"""
        system_prompt = (
            "你是一个精准的人物关系与情感分析专家。"
            "请仔细分析用户提供的文本，提取出其中所有人物之间的情感与关系。"
            "你必须以 json 格式返回结果，JSON 格式要求如下：\n"
            "{\n"
            '  "graph": [\n'
            "    {\n"
            '      "source": "关系的起点人物，如：小明",\n'
            '      "relation": "关系或情感类型，如：喜欢",\n'
            '      "target": "关系的终点人物，如：小姚"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"请分析以下文本的人物关系：\n{text}",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            # 解析返回的 JSON 字符串
            content = response.choices[0].message.content
            data = json.loads(content)

            # 使用 Pydantic 进行类型校验和过滤
            validated_data = RelationshipGraph(**data)
            return [
                relation.model_dump() for relation in validated_data.graph
            ]

        except Exception as e:
            print(f"分析出错: {e}")
            return []


# 3. 连续交互主循环
def main():
    agent = RelationshipAnalysisAgent()

    print("=" * 60)
    print("人物关系与情感分析 Agent (DeepSeek 版) 已启动")
    print("提示：输入文本后回车即可分析；输入 'exit' 或 'q' 退出程序。")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("请输入要分析的文本 > ").strip()

            if user_input.lower() in ["exit", "q", "quit", "退出"]:
                print("\n感谢使用，程序已退出！")
                break

            if not user_input:
                continue

            print("正在分析中...")
            relations = agent.analyze(user_input)

            print("\n分析结果（人物关系图谱）：")
            print(json.dumps(relations, ensure_ascii=False, indent=4))
            print("-" * 60 + "\n")

        except KeyboardInterrupt:
            print("\n\n程序已手动终止！")
            break


if __name__ == "__main__":
    main()