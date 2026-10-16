import asyncio
import json
import os

from agents import Agent, Runner, set_default_openai_api, set_tracing_disabled
from pydantic import BaseModel, ValidationError


# 将密钥设置在系统环境变量 OPENAI_API_KEY 中，不要把真实密钥写进代码。
# 本示例通过 DeepSeek 的 OpenAI 兼容接口调用模型。
os.environ["OPENAI_API_KEY"] = "sk-bf4240833topabub33dacd6be11"
os.environ["OPENAI_BASE_URL"] =  "https://api.deepseek.com"
set_default_openai_api("chat_completions")
set_tracing_disabled(True)


class TranslationOutput(BaseModel):

    query_input: str  # 用户输入的原文
    language: str     # 检测出的语种，例如“中文”“英语”“日语”
    result: str       # 翻译后的文本


translator_agent = Agent(
    name="Language Detector and Translator",
    model="deepseek-flash",  # TODO：按实际使用的模型修改
    instructions="""
你是一个语种识别与翻译助手。收到用户输入后，请完成以下任务：

1. 判断输入文本主要使用的语言，并用中文语言名称填写 language，例如“中文”“英语”“日语”“法语”。
2. 如果输入文本是中文，将原文翻译成自然、准确的英文。
3. 如果输入文本不是中文，将原文翻译成自然、准确的中文。
4. 如果输入中有多种语言，根据占主导的语言填写 language，并按上面的规则翻译整段文本。
5. query_input 必须逐字保留用户输入的原文；result 只填写译文，不添加解释、标题或引号。
6. 最终只输出一个合法 JSON 对象，且只能包含以下三个字段：
   - query_input：字符串，用户输入的原文
   - language：字符串，检测到的语言名称
   - result：字符串，翻译结果
7. 不要输出 Markdown 代码围栏、前言、结尾说明或 JSON 以外的内容。
""",

)


async def main():
    """读取文本，调用 Agent，校验并打印 JSON。"""

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("请先设置 OPENAI_API_KEY 环境变量，再运行程序。")

    query = input("请输入一段文本：").strip()
    if not query:
        print("输入不能为空。")
        return

    # 把用户输入传给 Agent；Runner.run 返回本次运行结果。
    run_result = await Runner.run(translator_agent, query)
    raw_output = run_result.final_output

    # 将模型返回的 JSON 字符串解析为 Pydantic 对象，并检查字段和类型。
    try:
        # 清除模型偶尔添加的 Markdown 代码围栏。
        json_text = raw_output.strip()
        if json_text.startswith("```json"):
            json_text = json_text[len("```json"):].strip()
        elif json_text.startswith("```"):
            json_text = json_text[len("```"):].strip()
        if json_text.endswith("```"):
            json_text = json_text[:-3].strip()

        output_data = json.loads(json_text)
        output = TranslationOutput.model_validate(output_data)
        # 原文由程序掌握，直接使用真实输入，避免模型改写 query_input。
        output.query_input = query
    except (json.JSONDecodeError, ValidationError) as error:
        print("模型输出不是符合要求的 JSON，或字段格式不正确：")
        print(error)
        print("模型原始输出：")
        print(raw_output)
        return

    # ensure_ascii=False 让中文正常显示；indent=4 用于美化 JSON 格式。
    print(output.model_dump_json(ensure_ascii=False, indent=4))


if __name__ == "__main__":
    asyncio.run(main())
