from agents import Agent, set_tracing_disabled
from agents import AsyncOpenAI, OpenAIChatCompletionsModel
from pydantic import BaseModel
from openai.types.responses import ResponseTextDeltaEvent
from agents.run import Runner
import os
import asyncio
import json

set_tracing_disabled(False)
client = AsyncOpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url=os.getenv("DEEPSEEK_URL"))

INSTRUCTIONS = """
你是一名多语种翻译专家，你需要判断用户输入的文本的语种，如果用户输入的是非中文，则翻译为中文；如果是中文，则翻译为英文。
最终输出json格式字符串
输出格式要求如下：
json：
{
    "query_input": "用户原始文本",
    "language": "原始文本语种",
    "result": "翻译结果"
}
不要输出 Markdown。
不要输出额外解释
"""


class TranslationResult(BaseModel):
    query_input: str
    language: str
    result: str


translation_agent = Agent(
    name="translation_agent",
    instructions=INSTRUCTIONS,
    model=OpenAIChatCompletionsModel(
        model="deepseek-flash",
        openai_client=client
    )
)


async def translate(text:str) -> TranslationResult:
    print(f"用户待翻译文本: {text}")
    result = await Runner.run(translation_agent, text)
    json_str = result.final_output
    json_result = json.loads(json_str)

    print(f"翻译结果: {json_result}")
    return TranslationResult(**json_result)

    # async for event in result.stream_events():
    #
    #     if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
    #         print(event.data.delta,end="",flush=True)


translation_result = asyncio.run(translate("الطقس جميل اليوم"))
print(translation_result)