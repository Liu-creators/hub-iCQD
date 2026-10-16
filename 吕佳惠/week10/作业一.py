import os

os.environ["OPENAI_API_KEY"] = "sk-xx"
os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"

from agents import Agent, Runner
from agents import set_default_openai_api, set_tracing_disabled
set_default_openai_api("chat_completions")
set_tracing_disabled(True)


# agent的定义
agent = Agent(
    model="deepseek-flash",
    name="LanguageTranslateAgent",
    instructions="""你是语种识别翻译Agent。
任务规则：
1. 识别用户输入文本是什么语言。
2. 如果原始文本是中文，翻译成英文；其他所有语言，翻译成中文。
3. 输出**严格JSON**，不能输出任何额外解释文字，JSON结构固定如下：
{
    "query_input": "用户原始输入文本",
    "language": "识别出的语言名称，例如：中文、英文、日语",
    "result": "翻译后的文本"
}
"""
)

# 接受用户输入，构建对话 调用大模型 得到输出
if __name__ == "__main__":
    user_input = input("请输入需要处理的文本：")
    result = Runner.run_sync(agent, user_input)
    print(result.final_output)
