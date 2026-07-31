from openai import OpenAI
import json

def safe_json_parse(text: str) -> dict | list | None:
    """安全解析 JSON，处理可能的空 content 和格式异常。"""
    if not text or not text.strip():
        print("    ⚠️  模型返回了空 content（JSON 模式偶发问题）")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"    ⚠️  JSON 解析失败: {e}")
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"    原始内容: {text[:200]}")
            return None

client = OpenAI(
    api_key = "sk-a811ef3194c549d5b6bba331428c69a4",
    base_url = "https://api.deepseek.com"
)

system_prompt = """用户会提供一段人物关系描述语句，请解析出人物关系图谱，包含了source(人名),relation(关系),target(人名)，
并且以JSON格式输出
**重要映射规则（必须严格遵守）**：
- 如果原文出现 "喜欢" → 输出关系为 "爱慕"
- 如果原文出现 "不喜欢" → 输出关系为 "讨厌"
- 如果原文出现 "讨厌" → 输出关系为 "讨厌"
- 其他关系请按常识推断，但上述规则优先级最高。
JSON输出示例：
[
{"source":"小张","relation":"爱慕","target":"小何"},
{"source":"小何","relation":"讨厌","target":"小吕"}
]
"""

user_prompt = """小明喜欢小姚，但是小姚喜欢小王"""

stream_response = client.chat.completions.create(
    model = "deepseek-v4-flash",
    messages = [
        {"role":"system","content":system_prompt},
        {"role":"user","content":user_prompt},
    ],
    response_format = {"type":"json_object"},
    stream = True,
    max_tokens = 500,
    temperature = 0.0,
)

full_content = ""
print("    流式接收中：",end = "",flush = True)
for chunk in stream_response:
    delta = chunk.choices[0].delta if chunk.choices else None
    if delta and delta.content:
        full_content += delta.content
        print(delta.content,end = "",flush = True)

result = safe_json_parse(full_content)

if result:
    items = result if isinstance(result,list) else result.get("items",result.get("source",[result]))
    print(f"\n共提取{len(items)}个人物关系图谱")
    for i,item in enumerate(items,1):
        print(f"第{i}条关系图谱：{item["source"]}--{item["relation"]}--{item["target"]}")
    print(f"\n模型原始输出:\n{json.dumps(result,ensure_ascii = False,indent = 2)}")
