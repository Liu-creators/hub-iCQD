from agent import get_agent
from agents import Runner
import asyncio

async def chat(input:str):
    async with get_agent() as agent:
        result = await Runner.run(agent,input)
        return result.final_output

result = asyncio.run(chat("你好，我叫小溪，我今天的运势怎么样?"))
print(result)