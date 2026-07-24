import json
from openai import OpenAI

client = OpenAI(
    api_key="sk-lgtqzewsvgvyvjaxxxabugasuxtpnjrapeymxmhstghyucbu",
    # 硅基流动官方兼容接口地址
    base_url="https://api.siliconflow.cn/v1"
)

#json output
#设置系统提示词


system_prompt = """
从输入句子中抽取人物三元组关系，严格输出JSON数组，规则：
1. person1、relation、target三个字段为必填，字段名绝对不能写错
2. 所有实体必须从输入文本中直接提取，不能凭空生成
3. 关系词用最简短的动词/动宾短语，比如"喜欢"直接映射为"爱慕"
示例：输入"小明喜欢小姚，但是小姚喜欢小王" → 
json输出示例
{
"relations": [
    {"person1":"小明","relation":"爱慕","target":"小姚"},
    {"person1":"小姚","relation":"爱慕","target":"小王"}
]
}
只返回纯JSON数组，不要任何解释、说明、markdown标记，不要用```json包裹内容
"""
#用户提示词
user_prompt = "小明讨厌小红，小明喜欢小王，小王喜欢小红"
#上下文
my_message = [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]

response = client.chat.completions.create(
    #设置模式
    model="deepseek-ai/DeepSeek-V3",
    #设置上下文
    messages=my_message,
    #设置格式为json
    response_format={
        "type": "json_object"
    },
    max_tokens=2047,  # 给足够的输出空间，避免内容被截断
    temperature=0.0,  # 调低温度，让模型输出更稳定、更服从指令，不会随机偷懒少输出内容
)

print(f"json mode 输出结果为：{json.loads(response.choices[0].message.content)}")


print(f"tool_calls方法")
#tool_calls方法
def analysis(person: str, relation: str, persion2:str) -> str:
    print("调用分析")
    return {"persion1":person,"relation":relation,"target":persion2}

TOOLS = [
    {
        "type":"function",
        "description":"通过传入的人物和情感，输出对应的关系",
        "function":{
            "name":"analysis",
            "properties":{
                "persion1":{
                    "type":"string",
                    "description":"人物名称，如小王，小红",
                },
                "relation":{
                    "type":"string",
                    "description":"情感，如喜欢，厌恶等",
                },
                "persion2":{
                    "type":"string",
                    "description":"目标人物名称",
                },
            },
            "required":["persion1","relation","persion2"],
        },
    },
]
#工具名到本地映射
FUNCTION_MAP = {
    "analysis": analysis,
}

messages = [
    {"role": "system", "content": "你是一个情感分析助手，您能根据输入的问题判断出他们的关系"},
    {"role": "user", "content": "小明讨厌小红，小明喜欢小王，小王喜欢小红"},
]

response = client.chat.completions.create(
    model="deepseek-ai/DeepSeek-V3",
    messages=messages,
    tools=TOOLS,
    #tool_choice={"type": "function", "function": {"name": "analysis"}},  #调用失败，无法分析出所需要的参数
    temperature=0.0,
)


#生成结构化的tool_calls指令
choice = response.choices[0]
msg = choice.message

def run_tool_call(tc) -> str:
    """执行一次工具调用，返回结果字符串。"""
    name = tc.function.name   #获取方法名称
    args = json.loads(tc.function.arguments)    #获取方法参数
    print(f"    → 调用工具: {name}({json.dumps(args, ensure_ascii=False)})")
    result = FUNCTION_MAP[name](**args)    #调用方法
    print(f"    ← 结果: {result}")
    return result

# 通过返回的tool_calls指令，发起工具调用
if msg.tool_calls:
    messages.append(msg)  # 保留 assistant 的 tool_calls
    for tc in msg.tool_calls:#方法名称
        result = run_tool_call(tc)#获取结果
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": result,
        })

    # 把工具结果发回模型，让其生成最终回复
    final = client.chat.completions.create(
        model="deepseek-ai/DeepSeek-V3",
        messages=messages,
        tools=TOOLS,
        temperature=0.0,
    )
    print(f"\n最终回复: {final.choices[0].message.content}")
else:
    print(f"直接回复: {msg.content}")

print()
