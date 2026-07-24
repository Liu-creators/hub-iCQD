"""
工具调用 (Tools / Function Calling) — 让模型调用外部函数

API 参考：https://platform.openai.com/docs/guides/function-calling
"""

import json
import math
from openai import OpenAI

client = OpenAI(
    api_key="sk-yfqejlbhabiovwcbxxxabujmifjrqbljjrypkeythx",
    base_url="https://api.siliconflow.cn/v1/",
)

# ═════════════════════════════════════════════════════════════════════════════
# 0. 定义本地工具函数
# ═════════════════════════════════════════════════════════════════════════════
def record_relationships(relations: list) -> str:
    """本地处理提取出的关系列表"""
    print("\n提取到的关系图谱（JSON）:")
    print(json.dumps(relations, ensure_ascii=False, indent=4))
    return "已成功记录关系"

# ═════════════════════════════════════════════════════════════════════════════
# 工具描述 schema（传给模型）
# ═════════════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "record_relationships",
            "description": "提取并记录文本中的人物关系图谱",
            "parameters": {
                "type": "object",
                "properties": {
                    "relations": {
                        "type": "array",
                        "description": "关系列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {
                                    "type": "string",
                                    "description": "关系发起人（如：小明）"
                                },
                                "relation": {
                                    "type": "string",
                                    "description": "关系名称（如：爱慕、喜欢）"
                                },
                                "target": {
                                    "type": "string",
                                    "description": "关系接收人（如：小姚）"
                                }
                            },
                            "required": ["source", "relation", "target"]
                        }
                    }
                },
                "required": ["relations"]
            }
        }
    }
]
# 工具名 → 本地函数映射
FUNCTION_MAP = {
    "record_relationships": record_relationships
}


def run_tool_call(tc) -> str:
    """执行一次工具调用，返回结果字符串。"""
    name = tc.function.name
    args = json.loads(tc.function.arguments)
    print(f"    → 调用工具: {name}({json.dumps(args, ensure_ascii=False)})")
    result = FUNCTION_MAP[name](**args)
    print(f"    ← 结果: {result}")
    return result

messages = [
    {"role": "system", "content": "你是人物关系提取专家，请使用工具记录文本中的人物关系。"},
    {"role": "user", "content": "小明喜欢小姚，但是小姚喜欢小王。"},
]

response = client.chat.completions.create(
    model="Pro/MiniMaxAI/MiniMax-M2.5",
    messages=messages,
    tools=TOOLS,
    tool_choice={"type": "function", "function": {"name": "record_relationships"}},
    temperature=0.0,
)

msg = response.choices[0].message

if msg.tool_calls:
    for tc in msg.tool_calls:
        func_name = tc.function.name

        args = json.loads(tc.function.arguments)
        
        FUNCTION_MAP[func_name](**args)
