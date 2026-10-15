import os
import asyncio
import json
from agents import Agent, Runner, OpenAIChatCompletionsModel, set_tracing_disabled, set_default_openai_api
from openai import AsyncOpenAI
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

deepseek_client = AsyncOpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
)

deepseek_model = OpenAIChatCompletionsModel(
    model="deepseek-flash",
    openai_client=deepseek_client,
)

agent = Agent(
    name="Language Detector & Translator",
    instructions="""你的任务：
1. 检测用户输入文本的语种，用中文描述（如"英语"、"日语"、"中文"）。
2. 如果语种是中文，将文本翻译为英文；否则翻译为中文。
3. 必须严格按以下 JSON 格式返回，不要包含任何其他文本或代码块标记：
{"query_input": "用户原始输入", "language": "检测到的语种", "result": "翻译后的文本"}""",
    model=deepseek_model,
)

async def main(text: str):
    result = await Runner.run(agent, text)
    # result.final_output 是模型返回的 JSON 字符串
    data = json.loads(result.final_output)
    print(json.dumps(data, ensure_ascii=False, indent=4))
    return data

if __name__ == "__main__":
    asyncio.run(main("Hello, how are you?"))