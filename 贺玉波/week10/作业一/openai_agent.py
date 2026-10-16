import os

os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com/"
os.environ["OPENAI_API_KEY"] = ""

import asyncio
from agents import Agent, InputGuardrail, GuardrailFunctionOutput, Runner
from agents.exceptions import InputGuardrailTripwireTriggered

from agents import set_default_openai_api, set_tracing_disabled
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

judge_agent = Agent(
    name="Language Translation Judge",
    model="deepseek-flash",
    instructions="判断用户输入的语言是否为中文。只能返回 true 或 false，不要返回 JSON 或其他文字。",
)

text_to_cn_agent = Agent(
    name="Language Translation Agent",
    model="deepseek-flash",
    instructions="您是专业的语言翻译专家。如果用户输入的是非中文，就将文本翻译为中文。请确保翻译准确、流畅，并保留原文的意思。",
    output_type=str,
)

text_to_en_agent = Agent(
    name="Language Translation Agent",
    model="deepseek-flash",
    instructions="您是专业的语言翻译专家。如果用户输入的是中文，就将中文翻译为英文。请确保翻译准确、流畅，并保留原文的意思。",
    output_type=str,
)


async def main():
    user_input = input("请输入文本（中文或非中文）：")
    
    # 运行语言判断代理
    judge_result = await Runner.run(judge_agent, user_input)
    is_chinese = judge_result.final_output.strip().lower() == "true"
    
    # 根据判断结果运行翻译代理
    if is_chinese:
        translation_result = await Runner.run(text_to_en_agent, user_input)
    else:
        translation_result = await Runner.run(text_to_cn_agent, user_input)
    translated_text = translation_result.final_output_as(str)
    
    print(f"\n[翻译结果] 原文: '{user_input}'")
    print(f"[翻译结果] 翻译后: '{translated_text}'")

if __name__ == "__main__":
    asyncio.run(main())