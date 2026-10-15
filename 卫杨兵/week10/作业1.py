import os
from agents import Agent, Runner
from agents import set_default_openai_api, set_tracing_disabled
from pydantic import BaseModel

set_default_openai_api("chat_completions")
set_tracing_disabled(True)

os.environ["OPENAI_API_KEY"] = "sk-1***01ce9****985cbbb8"
os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"


class ResultOutput(BaseModel):
    """用于判断语种并翻译输出结果的数据结构"""
    query_input: str  # 用户输入内容
    language: str  # 判断输入的语言
    result: str  # 翻译后的内容


# agent的定义
agent = Agent(
    model="deepseek-flash",
    name="Translator",
    instructions="""你是一个专业的翻译助手。对于输入，判断文本的语种（是什么语言的），如果是非中文的，则翻译为中文；如果是中文，则翻译为英文.
                    最终输出格式需要为json，例如：
                    #用户输入：今天天气真好
                    #判断语种：中文
                    #翻译结果：The weather is really nice today!
                    
                    {
                    "query_input": "今天天气真好",
                    "language": "中文",
                    "result": "The weather is really nice today!"
                    }

                 """
)

# 接受用户输入，构建对话 调用大模型 得到输出
query = input('请输入内容：')
result = Runner.run_sync(agent, query)

print(result.final_output)
