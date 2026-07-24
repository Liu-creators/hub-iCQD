from openai import OpenAI
import json

client = OpenAI(
    api_key="sk-e16dxxxabue43908ae4d922f96c4a8f",
    base_url="https://api.deepseek.com",
)
# ═════════════════════════════════════════════════════════════════════════════
# 1.  tool call输出
# ═════════════════════════════════════════════════════════════════════════════
print("=" * 65)
print("1️⃣  tool call输出")
print("=" * 65)

messages = [
    {"role": "system", "content": "根据用户描述提取人物情感关系"},
    {"role": "user", "content": "小明喜欢小姚，但是小姚喜欢小王"}
]
tools = [
    {
        "type": "function",
        "function": {
            "name": "extract_relationship",
            "description": "提取人物情感关系",
            "parameters": {
                "type": "object",
                "properties": {
                    "relationships": {
                        "type": "array",
                        "description": "关系列表，每个关系包含source（主体）、target（目标）、relation（关系类型）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string", "description": "关系的主体人物"},
                                "relation": {"type": "string", "enum": ["爱慕", "喜欢", "讨厌"],
                                             "description": "关系类型"},
                                "target": {"type": "string", "description": "关系的目标人物姓名"}
                            },
                            "required": ["source", "relation", "target"]
                        }
                    }
                },
                "required": ["relationships"]
            }
        }
    }
]

response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=messages,
    tools=tools,
)

msg = response.choices[0].message
if msg.tool_calls:
    args = json.loads(msg.tool_calls[0].function.arguments)
    result = args.get("relationships", [])
    print(json.dumps(result, ensure_ascii=False, indent=2))
else:
    print(f"直接回复: {msg.content}")

# ═════════════════════════════════════════════════════════════════════════════
# 2.  json mode输出
# ═════════════════════════════════════════════════════════════════════════════

print("=" * 65)
print("2️⃣   json mode输出")
print("=" * 65)

system_prompt = """
从用户的文字描述中提取人物关系信息，并以 JSON 格式输出，只输出结果不需要多余的内容：

输入示例：
张三喜欢李四

JSON 输出示例：
[
    {
        "source": "张三",
        "relation": "爱慕",
        "target": "李四"
    },
]

"""

user_prompt = "小明喜欢小姚，但是小姚喜欢小王"

response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    extra_body={"thinking": {"type": "disabled"}},
    response_format={"type": "json_object"},
    max_tokens=200,
    temperature=0.0,
)

content = response.choices[0].message.content
print(f"输出结果: {content}")
