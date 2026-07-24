import os
from openai import OpenAI

client = OpenAI(
    api_key="sk-***",
    base_url="https://api.deepseek.com")

system_prompt = """
用户会输入人物关系描述。请从中解析出人物关系并以 JSON 格式输出。

输入示例：
小明喜欢小姚，但是小姚喜欢小王。

JSON 输出示例：
[
  {
    "source": "小明",
    "relation": "爱慕"
    "target":"小姚"
  },
  {
    "source": "小姚",
    "relation": "爱慕"
    "target":"小王"
  },
]
"""

user_prompt = "叶凡喜欢宁婉儿，但是宁婉儿暗恋王晨。"

response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    stream=False,
    response_format={"type": "json_object"},
    reasoning_effort="high",
    extra_body={"thinking": {"type": "enabled"}}
)

print(response)
print(response.choices[0].message.content)
