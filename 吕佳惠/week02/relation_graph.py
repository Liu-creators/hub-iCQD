from dotenv import load_dotenv
import os
from openai import OpenAI
import json #JSON Output — 让模型输出结构化 JSON


# 加载当前目录下的.env文件
load_dotenv("llm.deepseek.env")

# 从环境变量读取配置
api_key = os.getenv("DEEPSEEK_API_KEY")
base_url = os.getenv("DEEPSEEK_BASE_URL")
model = os.getenv("MODEL_NAME")

# 校验密钥是否读取成功，防止空值报错
if not api_key:
    raise ValueError("未读取到DEEPSEEK_API_KEY，请检查.env文件配置")

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

# 初始化DeepSeek客户端
client = OpenAI(
    api_key=api_key,
    base_url=base_url
)

system_prompt = """
你是一个情感分析智能体。请从中解析出 "source" 和 "relation" 和 "target" 并以 JSON 格式输出。

输入示例：
小明喜欢小姚

输出：人物关系图谱 
JSON 格式输出示例：
[
    {
        "source": "小明",
        "relation": "爱慕",
        "target": "小姚"
    }
]
"""

user_prompt = "小明喜欢小姚，但是小姚喜欢小王。"

# 测试调用
response = client.chat.completions.create(
    model = model,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    response_format={"type": "json_object"},
    max_tokens=200,
    temperature=0.0
)
content = response.choices[0].message.content
result = safe_json_parse(content)

if result:
    print(f"\n输出:\n{json.dumps(result, ensure_ascii=False, indent=2)}")