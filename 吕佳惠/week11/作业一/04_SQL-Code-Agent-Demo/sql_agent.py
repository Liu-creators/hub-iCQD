import sqlite3
import sqlalchemy
import time
import jwt
import requests
from itertools import combinations
import numpy as np
from tqdm import tqdm
from typing import Union
import traceback
from sqlalchemy import create_engine, inspect, func, select, Table, MetaData, text
import pandas as pd
import os
from agents import Agent, Runner, function_tool, AsyncOpenAI, OpenAIChatCompletionsModel
from agents import set_default_openai_api, set_tracing_disabled
from typing import Annotated

# ===================== 环境配置（和你测试可用的版本保持一致） =====================
os.environ["OPENAI_API_KEY"] = "sk-"
os.environ["OPENAI_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"

set_default_openai_api("chat_completions")
set_tracing_disabled(True)

# 【关键：和你示例代码一模一样的创建方式，增加超时120s】
external_client = AsyncOpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ["OPENAI_BASE_URL"],
    timeout=120.0
)
qwen_max_model = OpenAIChatCompletionsModel(
    model="qwen-max",
    openai_client=external_client,
)

# ===================== DBParser 数据库解析模块（原样保留） =====================
class DBParser:
    '''DBParser 数据库的解析'''

    def __init__(self, db_url: str) -> None:
        '''初始化
        db_url: 数据库链接地址
        mysql: mysql://root:123456@localhost:3306/mydb?charset=utf8mb4
        sqlite: sqlite://chinook.db
        '''

        # 判断数据库类型
        if 'sqlite' in db_url:
            self.db_type = 'sqlite'
        elif 'mysql' in db_url:
            self.db_type = 'mysql'

        # 链接数据库
        self.engine = create_engine(db_url, echo=False)
        self.conn = self.engine.connect()
        self.db_url = db_url

        # 查看表明
        self.inspector = inspect(self.engine)
        self.table_names = self.inspector.get_table_names()  # 获取table信息

        self._table_fields = {}  # 数据表字段
        self.foreign_keys = []  # 数据库外键
        self._table_sample = {}  # 数据表样例

        # 依次对每张表的字段进行统计
        for table_name in self.table_names:
            print("Table ->", table_name)
            self._table_fields[table_name] = {}

            # 累计外键
            self.foreign_keys += [
                {
                    'constrained_table': table_name,
                    'constrained_columns': x['constrained_columns'],
                    'referred_table': x['referred_table'],
                    'referred_columns': x['referred_columns'],
                } for x in self.inspector.get_foreign_keys(table_name)
            ]

            # 获取当前表的字段信息
            table_instance = Table(table_name, MetaData(), autoload_with=self.engine)
            table_columns = self.inspector.get_columns(table_name)
            self._table_fields[table_name] = {x['name']: x for x in table_columns}

            # 对当前字段进行统计
            for column_meta in table_columns:
                # 获取当前字段
                column_instance = getattr(table_instance.columns, column_meta['name'])

                # 统计unique
                query = select(func.count(func.distinct(column_instance)))
                distinct_count = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta['name']]['distinct'] = distinct_count

                # 统计most frequency value
                field_type = self._table_fields[table_name][column_meta['name']]['type']
                field_type = str(field_type)
                if 'text' in field_type.lower() or 'char' in field_type.lower():
                    query = (
                        select(column_instance, func.count().label('count'))
                        .group_by(column_instance)
                        .order_by(func.count().desc())
                        .limit(1)
                    )
                    top1_value = self.conn.execute(query).fetchone()[0]
                    self._table_fields[table_name][column_meta['name']]['mode'] = top1_value

                # 统计missing个数
                query = select(func.count()).filter(column_instance == None)
                nan_count = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta['name']]['nan_count'] = nan_count

                # 统计max
                query = select(func.max(column_instance))
                max_value = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta['name']]['max'] = max_value

                # 统计min
                query = select(func.min(column_instance))
                min_value = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta['name']]['min'] = min_value

                # 任意取值
                query = select(column_instance).limit(10)
                random_value = self.conn.execute(query).all()
                random_value = [x[0] for x in random_value]
                random_value = [str(x) for x in random_value if x is not None]
                random_value = list(set(random_value))
                self._table_fields[table_name][column_meta['name']]['random'] = random_value[:3]

            # 获取表样例（第一行）
            query = select(table_instance)
            self._table_sample[table_name] = pd.DataFrame([self.conn.execute(query).fetchone()])
            self._table_sample[table_name].columns = [x['name'] for x in table_columns]

    def get_table_fields(self, table_name) -> pd.DataFrame:
        '''获取表字段信息'''
        return pd.DataFrame.from_dict(self._table_fields[table_name]).T

    def get_data_relations(self) -> pd.DataFrame:
        '''获取数据库链接信息（主键和外键）'''
        return pd.DataFrame(self.foreign_keys)

    def get_table_sample(self, table_name) -> pd.DataFrame:
        '''获取数据表样例'''
        return self._table_sample[table_name]

    def check_sql(self, sql) -> tuple[bool, str]:
        '''检查sql是否合理
        参数
            sql: 待执行句子
        返回: 是否可以运行 报错信息
        '''
        try:
            # 增加防护：禁止写操作
            danger_words = ["drop", "alter", "delete", "update", "insert", "create"]
            lower_sql = sql.lower()
            for w in danger_words:
                if w in lower_sql:
                    return False, f"禁止危险操作：{w}"
            with self.engine.begin() as conn:
                conn.execute(text(sql))
            return True, 'ok'
        except Exception as e:
            err_msg = traceback.format_exc()
            return False, err_msg

    def execute_sql(self, sql) -> list:
        '''运行SQL，返回结果列表'''
        with self.engine.begin() as conn:
            result = conn.execute(text(sql))
            rows = result.fetchall()
            cols = list(result.keys())
            res = [dict(zip(cols, row)) for row in rows]
        return res

# 初始化解析器
parser = DBParser('sqlite:///./chinook.db')

# ===================== Tool：查询表详情 =====================
@function_tool
def parse_table(table_name: Annotated[str, "The table name you want to view schema"]) -> str:
    """Return markdown table of field schema, stats and sample for given table."""
    field_df = parser.get_table_fields(table_name)
    sample_df = parser.get_table_sample(table_name)
    return f"### 表 {table_name} 字段信息\n{field_df.to_markdown()}\n\n### 表样例\n{sample_df.to_markdown()}"

# ===================== Agent 全部使用 qwen_max_model（和你示例结构统一） =====================
table_select_agent = Agent(
    name="TableSelectorAgent",
    model=qwen_max_model,
    instructions="""
你是SQL专家。根据用户的自然语言问题、可选表列表，选出查询需要用到的表。
你可以调用parse_table工具查看表结构。
输出要求：只输出表名，多个表用英文逗号分隔，不要多余解释。
""",
    tools=[parse_table]
)

sql_generate_agent = Agent(
    name="SqlGenerateAgent",
    model=qwen_max_model,
    instructions="""
根据用户问题、选中的表结构、字段统计信息，生成sqlite的SELECT查询SQL。
约束：
1. 只写SELECT，禁止任何修改表/数据语句
2. 适配sqlite语法，关键字表名用[]包裹
3. 只输出SQL文本，不要```markdown、不要解释
"""
)

sql_fix_agent = Agent(
    name="SqlFixAgent",
    model=qwen_max_model,
    instructions="""
原始SQL校验报错了，根据表schema、报错信息、用户问题，修正SQL语句。
只输出修正后的SQL，不要任何解释，仅sqlite SELECT。
"""
)

summary_agent = Agent(
    name="ResultSummaryAgent",
    model=qwen_max_model,
    instructions="""
你是结果汇总助手，根据用户原始问题、SQL查询返回的结构化数据，用通顺中文回答用户。
简洁易懂，不要输出原始json、不要输出SQL。
"""
)

# ===================== 完整SQL Agent Workflow 主函数 =====================
async def sql_agent_workflow(user_question: str):
    print("===== 步骤1：数据库解析（初始化DBParser已完成） =====")
    all_tables = parser.table_names
    print(f"数据库全部表：{all_tables}")

    print("\n===== 步骤2：表选择 Agent =====")
    table_select_prompt = f"用户问题：{user_question}\n可选数据表列表：{all_tables}"
    table_result = await Runner.run(table_select_agent, table_select_prompt)
    selected_tables = table_result.final_output.strip()
    print(f"选中表：{selected_tables}")

    print("\n===== 步骤3：SQL生成 Agent =====")
    schema_text = ""
    for t in selected_tables.split(","):
        t = t.strip()
        if t in all_tables:
            schema_text += f"\n==== Table {t} ====\n"
            schema_text += parser.get_table_fields(t).to_markdown()
    gen_prompt = f"用户问题：{user_question}\n选中表结构：{schema_text}"
    gen_result = await Runner.run(sql_generate_agent, gen_prompt)
    raw_sql = gen_result.final_output.strip()
    print(f"初始生成SQL：\n{raw_sql}")

    print("\n===== 步骤4：SQL校验 check_sql =====")
    valid, msg = parser.check_sql(raw_sql)
    print(f"校验结果：{msg}")
    final_sql = raw_sql

    if not valid:
        print("\n===== 步骤5：SQL改写 Agent（自动修复） =====")
        fix_prompt = f"""
用户问题：{user_question}
表结构：{schema_text}
原始SQL：{raw_sql}
报错信息：{msg}
请输出修正后的sqlite SELECT SQL
"""
        fix_result = await Runner.run(sql_fix_agent, fix_prompt)
        final_sql = fix_result.final_output.strip()
        print(f"改写修复后的SQL：\n{final_sql}")

    print("\n===== 步骤6：SQL执行 execute_sql =====")
    query_data = parser.execute_sql(final_sql)
    print(f"原始查询结果：{query_data}")

    print("\n===== 步骤7：结果汇总 Agent =====")
    sum_prompt = f"用户问题：{user_question}\n查询结果数据：{query_data}"
    sum_result = await Runner.run(summary_agent, sum_prompt)
    final_answer = sum_result.final_output
    print("\n✅ 最终回答：")
    print(final_answer)
    return final_answer

# ===================== 测试入口 =====================
if __name__ == "__main__":
    import asyncio
    test_question = "哪一位艺术家的专辑数量最多？"
    asyncio.run(sql_agent_workflow(test_question))
