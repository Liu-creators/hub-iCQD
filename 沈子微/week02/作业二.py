import json
from openai import OpenAI

# 初始化客户端
client = OpenAI(
    api_key="sk-kawntalubkjisxxxabuvcftcswqbddurowzfwfaeftbowt",
    base_url="https://api.siliconflow.cn/v1",
)

MODEL_NAME = "deepseek-ai/DeepSeek-V4-Flash"

# ═══════════════════════════════════════════════════════════
# 1. 定义工具 Schema（告诉大模型有哪些工具可用）
# ═══════════════════════════════════════════════════════════

TOOLS = [{
    "type": "function",
    "function": {
        "name": "add_relationship",
        "description": "从文本中提取人物之间的情感关系，每次调用记录一条关系",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "关系中的主动方（主语），如：小明、小姚"
                },
                "relation": {
                    "type": "string",
                    "description": "关系类型，用2-4个字描述，如：喜欢、讨厌、爱慕、暗恋、追求、依赖、嫌弃、恨等"
                },
                "target": {
                    "type": "string",
                    "description": "关系中的被动方（宾语），如：小姚、小王"
                }
            },
            "required": ["source", "relation", "target"]
        }
    }
}]


# ═══════════════════════════════════════════════════════════
# 2. 本地执行函数（真正的工具逻辑）
# ═══════════════════════════════════════════════════════════

def add_relationship(source: str, relation: str, target: str) -> dict:
    """
    记录一条人物关系。
    在实际项目中，这里可能是：存入数据库、写入文件、或触发其他业务逻辑。
    """
    # 简单返回结构化数据（也可以存到全局列表）
    return {
        "source": source,
        "relation": relation,
        "target": target,
    }


# 工具名 → 本地函数映射
FUNCTION_MAP = {
    "add_relationship": add_relationship,
}


def execute_tool_call(tool_call) -> dict:
    """执行单个工具调用，返回执行结果"""
    # 解析参数
    args = json.loads(tool_call.function.arguments)
    print(f"    🔧 执行工具: add_relationship({json.dumps(args, ensure_ascii=False)})")
    
    # 调用本地函数
    result = FUNCTION_MAP[tool_call.function.name](**args)
    print(f"    ✅ 执行成功: {result}")
    return result


# ═══════════════════════════════════════════════════════════
# 3. 主函数：情感分析智能体
# ═══════════════════════════════════════════════════════════

def sentiment_agent(user_input: str) -> list:
    """
    情感分析智能体主函数
    输入：自然语言文本
    输出：人物关系列表
    """
    print(f"\n📝 用户输入: {user_input}")
    print("-" * 50)
    
    # ---------- 第一步：调用大模型（带上工具定义） ----------
    messages = [
        {"role": "system", "content": "你是一个情感分析专家。请从用户输入的文本中提取所有人物的情感关系。"},
        {"role": "user", "content": user_input}
    ]
    
    print("🤖 第一次调用大模型：分析文本并决定调用哪些工具...")
    
    response = client.chat.completions.create(
        model= MODEL_NAME,
        messages=messages,
        tools=TOOLS,
        temperature=0.0,  # 降低随机性，提高稳定性
    )
    
    choice = response.choices[0]
    msg = choice.message
    
    # ---------- 第二步：检查大模型是否发起了工具调用 ----------
    if not msg.tool_calls:
        # 如果大模型没有调用工具，可能直接回复了文本
        print(f"⚠️  大模型未调用工具，直接回复: {msg.content}")
        return []
    
    print(f"📊 大模型发起了 {len(msg.tool_calls)} 个工具调用")
    
    # ---------- 第三步：执行所有工具调用 ----------
    relationships = []
    for tc in msg.tool_calls:
        result = execute_tool_call(tc)
        # 从结果中提取关系数据
        relationships.append({
            "source": result["source"],
            "relation": result["relation"],
            "target": result["target"]
        })
    
    # ---------- 第四步（可选）：第二次调用大模型，让它整理最终答案 ----------
    # 注意：这一步不是必须的，因为 tool_calls 已经包含了结构化数据
    # 这里演示如何让大模型生成更友好的回复
    
    # print("\n🤖 第二次调用大模型：生成最终回复...")
    
    # # 把工具调用结果加入到对话历史
    # messages.append(msg)  # 保留大模型的 tool_calls
    # for i, tc in enumerate(msg.tool_calls):
    #     messages.append({
    #         "role": "tool",
    #         "tool_call_id": tc.id,
    #         "content": json.dumps(relationships[i], ensure_ascii=False)
    #     })
    
    # # 让大模型基于工具结果生成最终回复
    # final_response = client.chat.completions.create(
    #     model=MODEL_NAME,
    #     messages=messages,
    #     temperature=0.0,
    # )
    
    # final_answer = final_response.choices[0].message.content
    # print(f"💬 最终回复: {final_answer}")
    
    return relationships


# ═══════════════════════════════════════════════════════════
# 4. jsonmode方式
# ═══════════════════════════════════════════════════════════

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

system_prompt = """
你是一个情感分析专家。请从用户输入的文本中提取所有人物的情感关系。

输出格式要求：
- 必须输出一个 JSON 数组
- 每个元素是一个对象，包含三个字段：
  - source: 关系中的主动方（人名）
  - relation: 关系类型（用2-4个字描述，如：喜欢、讨厌、爱慕、暗恋、追求、依赖等）
  - target: 关系中的被动方（人名）

输出示例：
{
    "relationships": [
        {"source": "小明", "relation": "喜欢", "target": "小姚"},
        {"source": "小姚", "relation": "喜欢", "target": "小王"}
    ]
}

注意：
1. 只输出 JSON 数组，不要有其他文字
2. 如果文本中没有明确的情感关系，输出空数组 []
"""

def jsonmode_agent(user_input: str) ->list:
    """
    基于jsonmode实现情感分析
    """
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role":"system","content":system_prompt},
            {"role":"user","content":user_input},
        ],
        response_format={"type":"json_object"},
        max_tokens=500,
        temperature=0.0
    )

    content =response.choices[0].message.content
    result = safe_json_parse(content)
    relationships = []
    if result:
        relationships = result.get("relationships", [])
    return relationships


# ═══════════════════════════════════════════════════════════
# 5. 测试运行
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 65)
    print("🧠 情感分析智能体 - Function Calling 完整实现")
    print("=" * 65)
    
    # 测试用例1：基本关系
    test1 = "小明喜欢小姚，但是小姚喜欢小王。"
    result1 = sentiment_agent(test1)
    print(f"\n📦 functioncall最终输出（结构化数据）:")
    print(json.dumps(result1, ensure_ascii=False, indent=2))
    jsonmode_result1 = jsonmode_agent(test1)
    print(f"\n jsonmode最终输出（结构化数据）:")
    print(json.dumps(jsonmode_result1, ensure_ascii=False, indent=2))
    
    print("\n" + "=" * 65)
    
    # 测试用例2：复杂情感
    test2 = "张三暗恋李四很久了，李四却对王五爱慕有加，王五非常讨厌赵六。"
    result2 = sentiment_agent(test2)
    print(f"\n📦 functioncall最终输出（结构化数据）:")
    print(json.dumps(result2, ensure_ascii=False, indent=2))
    jsonmode_result2 = jsonmode_agent(test2)
    print(f"\n jsonmode最终输出（结构化数据）:")
    print(json.dumps(jsonmode_result2, ensure_ascii=False, indent=2))
    
    print("\n" + "=" * 65)
    
    # 测试用例3：更复杂的场景
    test3 = "公司里，项目经理老王很器重小张，但小张却对产品经理小美有好感，小美一直暗恋着技术总监老李。"
    result3 = sentiment_agent(test3)
    print(f"\n📦 functioncall最终输出（结构化数据）:")
    print(json.dumps(result3, ensure_ascii=False, indent=2))
    jsonmode_result3 = jsonmode_agent(test3)
    print(f"\n jsonmode最终输出（结构化数据）:")
    print(json.dumps(jsonmode_result3, ensure_ascii=False, indent=2))
