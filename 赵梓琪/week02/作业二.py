import os
import json
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

# ═════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═════════════════════════════════════════════════════════════════════════════

def safe_json_parse(text: str) -> dict | list | None:
    """安全解析 JSON，处理可能的空 content 和格式异常。"""
    if not text or not text.strip():
        print("    ⚠️  模型返回了空 content（JSON 模式偶发问题）")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"    ⚠️  JSON 解析失败: {e}")
        # 尝试修复常见问题：删除 markdown 代码块标记
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"    原始内容: {text[:200]}")
            return None

# 定义给LLM调用的函数
def extract_relation(source: str, relation: str, target: str):
    """
    保存人物关系
    """
    result = [
        {
            "source": source,
            "relation": relation,
            "target": target
        }
    ]
    return json.dumps(
        result,
        ensure_ascii=False
    )

# Tool描述
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "extract_relation",
            "description": "提取人物之间的关系",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "关系发起者"
                    },
                    "relation": {
                        "type": "string",
                        "description": "人物关系，例如爱慕、朋友、同事"
                    },
                    "target": {
                        "type": "string",
                        "description": "关系目标"
                    }
                },
                "required": [
                    "source",
                    "relation",
                    "target"
                ]
            }
        }
    }
]

# 方法1: 调用LLM Tool Call
def llm_tool_call(text: str):
    """
    调用LLM工具
    """
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {
                "role":"system",
                "content":
                """
                你是人物关系抽取智能体。阅读用户输入。识别 source、relation、target。然后调用 extract_relation 函数，不要直接回答。
                """
            },
            {
                "role":"user",
                "content":
                text
            }
        ],
        tools=TOOLS,
        tool_choice={
            "type":"function",
            "function":{
                "name":"extract_relation"
            }
        },
        temperature=0.0,
        extra_body={
            "thinking":{
                "type":"disabled"
            }
        }
    )
    message = response.choices[0].message
    
    if not message.tool_calls:
        raise RuntimeError("模型没有调用Tool")
    tool_calls = message.tool_calls[0]
    args = safe_json_parse(
        tool_calls.function.arguments
    )
    if args is None:
        raise RuntimeError("Tool参数解析失败")
    
    return extract_relation(**args)

# 方法2: json mode
def json_mode(text: str):
    """
    调用LLM工具
    """
    system_prompt = """
    你是一个人物关系抽取智能体，请从输入文本中提取人物关系，并以 JSON 格式输出。
    输入示例：
    小明爱慕小姚
    JSON 输出示例：
    {
        "source": "小明",
        "relation": "爱慕",
        "target": "小姚"
    }
    """

    user_prompt = f"""
    请从以下文本中提取人物关系：
    {text}
    """

    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    )
    return safe_json_parse(response.choices[0].message.content)

if __name__ == "__main__":
    text = "小明爱慕小姚"
    print(llm_tool_call(text))
    print(json_mode(text))