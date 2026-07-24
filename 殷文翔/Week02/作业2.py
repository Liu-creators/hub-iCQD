import os
from openai import OpenAI
from dotenv import load_dotenv
import json
from typing import List, Dict

"""
作业2: 借助于llm tool call 或 json mode 能力，构建一个简单的情况情感分析智能体。提交实现代码。

输入：小明喜欢小姚，但是小姚喜欢小王。
输出：人物关系图谱

[
    {
        "source": "小明",
        "relation": "爱慕",
        "target": "小姚"
    }
]
"""

load_dotenv()

client = OpenAI(
    api_key=os.getenv("API_KEY"),
    base_url="https://api.deepseek.com"
)

user_input = "蜡笔小新喜欢奥特曼，不喜欢光头强"


# 1.Json格式输出结果
def emotion_relation_agent(userinput: str) -> List[Dict]:
    """
    情感人物关系分析智能体
    :param userinput: 自然语言情感场景文本
    :return: 标准化人物关系图谱
    """
    system_prompt = """你是一个情感关系分析专家,你需要根据用户提供的文本，对文本中出现的人物进行情感分析，并以JSON的格式输出人物关系图谱。
    规则：
        1. 只抽取人与人之间情感、爱慕、喜欢、讨厌、暗恋等情感关系
        2. 输出固定字段：source(发起人物)、relation(关系词)、target(目标人物)
        3. 必须纯JSON数组，无多余解释、无markdown、无额外文字
        4. 关系词简洁统一：喜欢、爱慕、暗恋、讨厌、嫌弃、思念等
    例如：
    输入：小明喜欢小姚，但是小姚喜欢小王。
    输出：
    [
        {
            "source": "小明",
            "relation": "爱慕",
            "target": "小姚"
        },
        {
            "source": "小姚",
            "relation": "爱慕",
            "target": "小王"
        }
    ]
    """

    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": userinput},
        ],
        response_format={"type": "json_object"},
    )
    result = response.choices[0].message.content
    return json.loads(result)


print(f"要求输出JSON格式：\n"
      f"用户输入：{user_input}\n")
answer = json.dumps(emotion_relation_agent(user_input), ensure_ascii=False, indent=2)
print(f"AI输出: {answer}")
print("-" * 30)
print("-" * 30)

# 2.调用工具完成任务

from itertools import combinations  # 从序列里 不重复、不分顺序 选出指定个数的组合
import random

# 关系词放在元组中，后续 random.choice 会随机选一个
RELATIONSHIPS = (
    "倾佩", "喜欢", "爱慕", "信任", "尊敬", "欣赏",
    "关心", "依赖", "支持", "感激", "敬畏",
    "想念", "牵挂", "保护", "崇拜",
    "讨厌", "厌恶", "嫉妒", "怀疑", "戒备",
    "畏惧", "轻视", "怨恨", "敌视", "责怪",
    "不信任", "排斥",
)


def relationship(entity1: str, entity2: str, entities: list[str] | None = None, ) -> str:
    """
    随机生成多个实体之间的关系描述。
    entity1、entity2：前两个必填人物
    *entities：后续可继续传入任意数量的人物
    """
    # 1. 将所有人物放到一个列表中
    # 例如 relationship("小明", "小红", "小刚")
    # 得到 ["小明", "小红", "小刚"]
    all_entities = [entity1, entity2, *(entities or [])]
    # 2. 检查人物名称是否为空
    # any(...) 只要发现一个空名称，就会返回 True
    if any(not isinstance(entity, str) or not entity.strip()
           for entity in all_entities):
        return "实体名称必须是非空字符串。"

    # 3. 去除人物名称两端的空格
    all_entities = [entity.strip() for entity in all_entities]

    # 4. 检查是否有重名人物
    # set 会自动去重；数量变少就代表有重复
    if len(set(all_entities)) != len(all_entities):
        return "实体名称不能重复，否则关系描述会有歧义。"

    # 5. 生成所有“两两组合”
    # 例如 ["小明", "小红", "小刚"]
    # 会得到：
    # [("小明", "小红"), ("小明", "小刚"), ("小红", "小刚")]
    pairs = list(combinations(all_entities, 2))

    # 6. 随机决定生成多少条关系
    # 最少 1 条，最多约为所有配对数量的一半
    relation_count = random.randint(1, max(1, (len(pairs) + 1) // 2))

    # 7. 从所有人物配对中随机抽取若干对
    # sample 不会重复抽取，所以同一对人物只会出现一次
    selected_pairs = random.sample(pairs, relation_count)

    # 用来保存最终生成的每一条关系
    result = []

    # 8. 逐对生成关系
    for person_a, person_b in selected_pairs:
        # 随机决定关系方向
        # 可能是“小明喜欢小红”
        # 也可能是“小红喜欢小明”
        source, target = random.choice(
            ((person_a, person_b), (person_b, person_a))
        )

        # 从关系词中随机选择一个
        relation = random.choice(RELATIONSHIPS)

        # 组成一条完整描述，例如“小明喜欢小红”
        result.append(f"{source}{relation}{target}")

    # 9. 用中文分号连接所有关系，并在结尾加句号
    return "；".join(result) + "。"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "relationship",
            "description": "接收人物实体名称，返回人物关系描述",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity1": {"type": "string", "description": "第一个实体名称"},
                    "entity2": {"type": "string", "description": "第二个实体名称"},
                    "entities": {"type": "array", "items": {"type": "string"}, "description": "其他实体名称"},
                },
                "required": ["entity1", "entity2"],
            },
        },
    },
]
# 工具名 → 本地函数映射
FUNCTION_MAP = {
    "relationship": relationship,
}


def run_tool_call(tc) -> str:
    """执行一次工具调用，返回结果字符串。"""
    name = tc.function.name
    args = json.loads(tc.function.arguments)
    print(f"    → 调用工具: {name}({json.dumps(args, ensure_ascii=False)})")
    result = FUNCTION_MAP[name](**args)
    print(f"    ← 结果: {result}")
    return result


def emotion_relation_agent_bytool(userinput: str) -> List[Dict]:
    system_prompt = """你是一个人际情感分析专家,你需要根据用户的提问，给出人际关系情感分析结果并以JSON格式输出。
必须先调用relationship工具来获取人物关系描述。
JSON输出示例，每个关系包含以下字段:
[{
    "source": "文本中的人物",
    "relationship": "文本中的人物之间的情感关系",
    "target": "文本中的人物"
}]

例如:用户输入"小明,小明老师之间有什么情感关系?"，你需要输出:
[{
    "source": "小明",
    "relationship": "倾佩",
    "target": "小明的老师"
}]

"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": userinput},
    ]

    # 模型可能需要多次调用工具
    for _ in range(5):
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            response_format={"type": "json_object"},
        )
        msg = response.choices[0].message
        if msg.tool_calls:
            # assistant 的 tool_calls 消息只能添加一次
            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                result = run_tool_call(tc)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            break
    return json.loads(msg.content)


user_input = "喜羊羊，光头强，蜡笔小新之间有什么情感关系?"
print(f"让AI使用工具进行解析并输出Json：\n"
      f"用户输入：{user_input}\n")
answer = json.dumps(emotion_relation_agent_bytool(user_input), ensure_ascii=False, indent=2)
print(f"AI输出: {answer}")
