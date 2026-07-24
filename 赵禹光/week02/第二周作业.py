import json
from openai import OpenAI

client = OpenAI(
    api_key="",
    base_url="https://api.deepseek.com",
)


# ---- 方式1: json mode ----

def get_relations_by_json(text):
    """让大模型直接输出关系json，解析后返回列表"""
    system = """
从文本中抽取人物关系，以json格式输出。
字段: source(发出者), relation(关系类型), target(接收者)

{
    "relationships": [
        {"source": "小明", "relation": "喜欢", "target": "小姚"}
    ]
}
只输出json，不要废话。
"""

    resp = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    content = resp.choices[0].message.content
    data = json.loads(content)
    return data.get("relationships", [])


# ---- 方式2: tool call ----

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_relation",
            "description": "记录一条人物关系",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "关系发出者"},
                    "relation": {"type": "string", "description": "关系类型，2-4个字"},
                    "target": {"type": "string", "description": "关系接收者"},
                },
                "required": ["source", "relation", "target"],
            },
        },
    }
]


def get_relations_by_tools(text):
    """让大模型通过函数调用来逐条记录关系"""
    messages = [
        {"role": "system", "content": "你是人物关系抽取助手，用 add_relation 工具记录每条关系。"},
        {"role": "user", "content": text},
    ]

    relations = []

    for _ in range(3):  # 最多3轮
        resp = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            tools=TOOLS,
            temperature=0.0,
        )

        msg = resp.choices[0].message

        if not msg.tool_calls:
            break

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            relations.append({
                "source": args["source"],
                "relation": args["relation"],
                "target": args["target"],
            })

        # 把工具调用和结果塞回对话
        messages.append(msg)
        for tc in msg.tool_calls:
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": "ok",
            })

    return relations

if __name__ == "__main__":
    tests = [
        "小明喜欢小姚，但是小姚喜欢小王。",
        "张三暗恋李四很久了，但李四只把张三当朋友。",
        "小红和小刚是好朋友，但小红讨厌小刚的弟弟小明。",
    ]

    for t in tests:
        print(f"\n输入: {t}")

        # json mode
        r1 = get_relations_by_json(t)
        print("  [json模式]", json.dumps(r1, ensure_ascii=False))

        # tool call
        r2 = get_relations_by_tools(t)
        print("  [tool模式]", json.dumps(r2, ensure_ascii=False))
