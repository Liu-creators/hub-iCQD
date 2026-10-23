import os
import asyncio
from typing import Annotated
from agents import Agent, Runner, function_tool
from sql_agent import DBParser
from pydantic import BaseModel, Field
from agents import set_tracing_disabled

"""
sql agent：
- table select：结合用户提问，选择表； 手动进行推理
- sql generator： 结合选择的提问 + 表 生成sql
- sql execute （sql 是 llm 生成的，可能会报错）：
    parser.check_sql("SELECT COUNT(DISTINCT ArtistId) FROM albums;")
    sql rewrtite： 基于已有sql + 用户输入 + 报错信息
- answer summary：
"""

set_tracing_disabled(True)
os.environ["OPENAI_API_KEY"] = "sk-100c01***44798***"
os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"

parser = DBParser('sqlite:///./chinook.db')


@function_tool
def parse_table(table_name: Annotated[str, "The table name"]) -> str:
    """Return filed of the given table."""
    return parser.get_table_fields(table_name).to_markdown


class TableSelectOrSql(BaseModel):
    """表结构选择或者sql生成 Agent 的结构化结果"""

    result: str = Field(description="识别出的表名或生成的sql语句")


class SQLTableSelectAgent:
    """表结构选择"""

    def __init__(self):
        self.thinking_agent = Agent(
            name="SQL Planer",
            instructions="你是一个专业的SQL专家，请分析在给定的表中哪一个表可以用来回答问题，只识别输出表名",
            model="deepseek-flash",
            output_type=TableSelectOrSql
        )

    async def run(self, question: str):
        result = await Runner.run(self.thinking_agent,
                                  input=f"用户提问如下：{question}\n\n\n可选择的表格有：{parser.table_names}")
        return result.final_output


# sql生成
class SQLGeneratorAgent:
    """生成sql"""

    def __init__(self):
        self.generator_agent = Agent(
            name="SQL Generator",
            instructions=f"你是一个专业的SQL生成专家，根据用户提问和表名生成相应的sql语句，并只输出相应的sql语句。",
            model="deepseek-flash",
            tools=[parse_table],
            output_type=TableSelectOrSql
        )

    async def run(self, message):
        result = await Runner.run(self.generator_agent, message)
        return result.final_output


async def execute(generate_agent, question, table_name, retry_time):
    """执行正确sql"""
    messages = [{
        "role": "user",
        "content": f"用户提问如下：{question}\n\n\n表名：{table_name}"
    }]
    for retry_idx in range(retry_time):  # 尝试次数
        result = await generate_agent.run(messages)
        sql = result.result
        print(f'第{retry_idx + 1}次生成sql为：{sql}')
        execute_is_success, msg = parser.check_sql(sql)
        if execute_is_success:
            r = parser.execute_sql(sql)
            return r
        messages.append({
            "role": "user",
            "content": f"上述sql语句执行存在错误，错误信息为{msg}，请在原有sql 【{sql}】基础上进行改进。"
        })
    return 'sql生成失败，未能正确查询到数据库结果！！'


# 对执行结果总结 -》 得到输出
class SQLResultSummaryAgent:
    """问题总结"""

    def __init__(self):
        self.summary_agent = Agent(
            name="question Summary",
            instructions="你是一个专业的问题专家，根据用户提问和从数据库中查询出来的结果总结回答。",
            model="deepseek-flash",
        )

    async def run(self, question: str, data):
        result = await Runner.run(self.summary_agent,
                                  input=f"用户提问如下：{question}\n\n\n数据库查询结果：{data}")
        return result.final_output


async def main(query):
    table_select = SQLTableSelectAgent()
    table_select_result = await table_select.run(query)  # 表选择
    print(f'选择的表名为：{table_select_result.result}')
    sql_generator = SQLGeneratorAgent()
    sql_generator_result = await execute(sql_generator, query, table_select_result.result, 3)  # sql生成并执行
    print(f'查询结果为：{sql_generator_result}')
    summary = SQLResultSummaryAgent()
    result_summary = await summary.run(query, sql_generator_result)  # 问题总结
    print(result_summary)


if __name__ == '__main__':
    q = '帮我统计下消费者有多少人？'
    asyncio.run(main(q))
