from typing import Union
from sqlalchemy import create_engine, inspect, func, select, Table, MetaData, text
import pandas as pd
import traceback
import asyncio
from agents import set_default_openai_api, set_tracing_disabled
set_default_openai_api("chat_completions")
set_tracing_disabled(True)
import os
import re
from typing import Annotated
from agents import Agent, Runner, function_tool

class DBParser:
    def __init__(self, db_url: str) -> None:
        # 判断数据库类型
        if 'sqlite' in db_url:
            self.db_type = 'sqlite'
        elif 'mysql' in db_url:
            self.db_type = 'mysql'
        else:
            raise ValueError(f"Unsupported db_url: {db_url}")
        # 链接数据库
        self.engine = create_engine(db_url, echo=False)
        self.conn = self.engine.connect()
        self.db_url = db_url
        # 查看表名
        self.inspector = inspect(self.engine)   # inspector 是 SQLAlchemy 专门用来读元数据（metadata）的对象。它不查业务数据，只查"结构描述"
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
                    'constrained_table': table_name, # 外键所在的表（子表）
                    'constrained_columns': x['constrained_columns'], # 子表的哪个字段是外键
                    'referred_table': x['referred_table'], # 被引用的表（父表）
                    'referred_columns': x['referred_columns'], # 父表的哪个字段被引用
                } for x in self.inspector.get_foreign_keys(table_name)
            ]
            # 获取当前表的字段信息
            table_instance = Table(table_name, MetaData(), autoload_with=self.engine)
            # Table('albums', MetaData(),
            #       Column('AlbumId', INTEGER(), ...),
            #       Column('Title', NVARCHAR(length=160), ...),
            #       Column('ArtistId', INTEGER(), ...), schema=None)
            table_columns = self.inspector.get_columns(table_name)
            # table_columns = [
            #     {
            #         'name': 'AlbumId',
            #         'type': INTEGER(),
            #         'nullable': False,
            #         'default': None,
            #         'autoincrement': True,
            #         'primary_key': 1,
            #         'comment': None,
            #     },
            #     {
            #         'name': 'Title',
            #         'type': NVARCHAR(length=160),
            #         'nullable': False,
            #         'default': None,
            #         'autoincrement': False,
            #         'primary_key': 0,
            #         'comment': None,
            #     },
            #     {
            #         'name': 'ArtistId',
            #         'type': INTEGER(),
            #         'nullable': False,
            #         'default': None,
            #         'autoincrement': False,
            #         'primary_key': 0,
            #         'comment': None,
            #     },
            # ]
            self._table_fields[table_name] = {x['name']: x for x in table_columns}
            # self._table_fields['albums'] = {
            #     'AlbumId': {
            #         'name': 'AlbumId',
            #         'type': INTEGER(),
            #         'nullable': False,
            #         'default': None,
            #         'autoincrement': True,
            #         'primary_key': 1,
            #         'comment': None,
            #     },
            #     'Title': {
            #         'name': 'Title',
            #         'type': NVARCHAR(length=160),
            #         'nullable': False,
            #         'default': None,
            #         'autoincrement': False,
            #         'primary_key': 0,
            #         'comment': None,
            #     },
            #     'ArtistId': {
            #         'name': 'ArtistId',
            #         'type': INTEGER(),
            #         'nullable': False,
            #         'default': None,
            #         'autoincrement': False,
            #         'primary_key': 0,
            #         'comment': None,
            #     },
            # }
            # 对当前字段进行统计
            for column_meta in table_columns:
                # 获取当前字段
                column_instance = getattr(table_instance.columns, column_meta['name'])
                #Column('AlbumId', INTEGER(), primary_key=True, nullable=False, ...)

                # 统计unique
                query = select(func.count(func.distinct(column_instance)))
                distinct_count = self.conn.execute(query).fetchone()[0]
                self._table_fields[table_name][column_meta['name']]['distinct'] = distinct_count
                # self._table_fields['albums']['AlbumId'] 变成：
                # {
                #     'name': 'AlbumId',
                #     'type': INTEGER(),
                #     'nullable': False,
                #     'default': None,
                #     'autoincrement': True,
                #     'primary_key': 1,
                #     'comment': None,
                #     'distinct': 347,  # ← 新增
                # }
                # 统计most frequency value  众数告诉你"这张表主要被哪个国家/类别占据" 这就是"字段画像"的智能之处：不同类型做不同统计。数值看分布，文本看众数 数值字段更关心 max / min / avg
                field_type = self._table_fields[table_name][column_meta['name']]['type']
                field_type = str(field_type)
                if 'text' in field_type.lower() or 'char' in field_type.lower():
                    query = (
                        select(column_instance, func.count().label('count')) #SELECT "invoices"."BillingCountry", count(*) AS count FROM invoices
                        .group_by(column_instance)
                        .order_by(func.count().desc()) # 降序
                        .limit(1) #只取第一组 —— 就是"出现次数最多的那一组" = 众数
                    )
                    top1_value = self.conn.execute(query).fetchone()[0] # .fetchone()取结果集第一行
                    self._table_fields[table_name][column_meta['name']]['mode'] = top1_value
                    # {
                    #     'name': 'BillingCountry',
                    #     'type': NVARCHAR(length=40),
                    #     'nullable': True,
                    #     'default': None,
                    #     'primary_key': 0,
                    #     'distinct': 24,
                    #     'nan_count': 0,
                    #     'mode': 'USA',  # ← 新增
                    #     # max/min/random 后面还会继续塞
                    # }
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

                # 任意取值    给每个字段随便取前 10 行的值，去重、转字符串、扔掉 None，最后只留 3 个，存进 random 字段。 目的：让 LLM 知道"这个字段的值长什么样"——是数字、是日期、是中文、是英文、是 USA 还是 United States？
                query = select(column_instance).limit(10)
                random_value = self.conn.execute(query).all()
                # [
                #     ('USA',),
                #     ('Canada',),
                #     ('USA',),
                #     ('Brazil',),
                #     ('USA',),
                #     ('Canada',),
                #     ('USA',),
                #     ('USA',),
                #     ('USA',),
                #     ('France',)
                # ]
                random_value = [x[0] for x in random_value] #从"每行是元组"里取出第一列
                # ['USA', 'Canada', 'USA', 'Brazil', 'USA', 'Canada', 'USA', 'USA', 'USA', 'France']
                random_value = [str(x) for x in random_value if x is not None] #转字符串，同时过滤掉 None
                random_value = list(set(random_value)) #去重
                self._table_fields[table_name][column_meta['name']]['random'] = random_value[:3] # 只保留前 3 个，存进画像

            # 获取表样例（第一行）
            query = select(table_instance) # SELECT * FROM albums
            self._table_sample[table_name] = pd.DataFrame([self.conn.execute(query).fetchone()]) #取结果集的第一行
            self._table_sample[table_name].columns = [x['name'] for x in table_columns]
        self.conn.close()

    def get_table_fields(self, table_name) -> pd.DataFrame:
        '''获取表字段信息'''
        return pd.DataFrame.from_dict(self._table_fields[table_name]).T
    # self._table_fields['albums'] = {
    #     'AlbumId': {
    #         'name': 'AlbumId',
    #         'type': INTEGER(),
    #         'nullable': False,
    #         'primary_key': 1,
    #         'distinct': 347,
    #         'nan_count': 0,
    #         'max': 347,
    #         'min': 1,
    #         'random': ['1', '3', '9'],
    #     },
    #     'Title': {
    #         'name': 'Title',
    #         'type': NVARCHAR(160),
    #         'nullable': False,
    #         'primary_key': 0,
    #         'distinct': 347,
    #         'nan_count': 0,
    #         'max': '[1997] Black Light Syndrome',
    #         'min': '...And Justice For All',
    #         'random': ['For Those About To Rock...', 'Big Ones', ...],
    #         'mode': '[1997] Black Light Syndrome',
    #     },
    #     'ArtistId': {
    #         'name': 'ArtistId',
    #         'type': INTEGER(),
    #         'nullable': False,
    #         'primary_key': 0,
    #         'distinct': 204,
    #         'nan_count': 0,
    #         'max': 275,
    #         'min': 1,
    #         'random': ['1', '3', '6'],
    #     },
    # }
    # 处理后
    #           name           type  distinct  nan_count ...
    #  AlbumId  AlbumId     INTEGER()       347          0 ...
    #  Title      Title  NVARCHAR(160)       347          0 ...
    #  ArtistId ArtistId    INTEGER()        204          0 ...

    def get_data_relations(self) -> pd.DataFrame:
        '''获取数据库链接信息（主键和外键）'''
        return pd.DataFrame(self.foreign_keys)

    def get_table_sample(self, table_name) -> pd.DataFrame:
        '''获取数据表样例'''
        return self._table_sample[table_name]

    def check_sql(self, sql) -> Union[bool, str]:
        '''检查sql是否合理

        参数
            sql: 待执行句子

        返回: 是否可以运行 报错信息
        '''
        try:
            with self.engine.begin() as conn:  # begin() 会自动提交和关闭，如果用self.engine.connect()得自己关
                conn.execute(text(sql))
            return True, 'ok'
        except:
            err_msg = traceback.format_exc() #把当前异常，格式化成字符串返回
            return False, err_msg

    def execute_sql(self, sql) -> bool:
        '''运行SQL'''

        with self.engine.begin() as conn:  # begin() 会自动提交和关闭
            result = conn.execute(text(sql))

        return list(result)



parser = DBParser('sqlite:///./chinook.db')
os.environ["OPENAI_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]
os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"

@function_tool
def parse_table(table_name: Annotated[str, "The table name"]) -> str:
    """Return the field metadata (name, type, distinct, mode...) of the given table."""
    return parser.get_table_fields(table_name).to_markdown()
@function_tool
def parse_sample(table_name: Annotated[str, "The table name"]) -> str:
    """Return the first row (sample data) of the given table."""
    return parser.get_table_sample(table_name).to_markdown()
@function_tool
def list_relations() -> str:
    """Return all foreign key relations in the database (for JOIN)."""
    return parser.get_data_relations().to_markdown()

def clean_sql(text: str) -> str:
    """从 LLM 输出中剥离 markdown 代码块，返回纯净 SQL（带结尾分号）"""
    if not text:
        return ""
    # 若有 ``` ... ``` 代码块，优先取块内内容
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(1)
    text = text.strip().strip("`").strip()
    # 去掉开头可能残留的 'sql'
    if text.lower().startswith("sql"):
        text = text[3:].strip()
    # 统一一个结尾分号
    text = text.rstrip(";").strip() + ";"
    return text
# 表结构选择
class SQLTableSelectAgent:
    def __init__(self):
        self.thinking_agent = Agent(
            name="SQL Planer",
            instructions="你是一个专业的SQL专家，请分析在给定的表中哪一个表可以用来回答问题。",
            model="deepseek-flash",
            tools=[parse_table],
        )

    async def run(self, question: str):
        result = await Runner.run(self.thinking_agent, input=f"用户提问如下：{question}\n\n\n可选择的表格有：{parser.table_names}")
        return result
# 根据用户问题生成SQL
class SQLGeneratorAgent:
    def __init__(self):
        self.agent = Agent(
            name="SQL Generator",
            instructions=(
                "你是一个专业的 SQLite SQL 专家。请根据用户问题和给定的表名，"
                "先用工具查看表结构、样例数据、外键关系，然后生成一条可执行的 SELECT 语句。\n"
                "要求：\n"
                "1. 只能使用数据库中真实存在的表名和字段名\n"
                "2. 只输出一条 SQL 语句，不要解释，不要加 markdown 代码块\n"
                "3. 必须是 SELECT 语句（禁止 INSERT/UPDATE/DELETE/DROP 等）\n"
                "4. 需要统计'多少个不同值'时，用 COUNT(DISTINCT ...)"
            ),
            model="deepseek-flash",
            tools=[parse_table, parse_sample, list_relations],
        )

    async def run(self, question: str, table_names: list[str]) -> str:
        prompt = (
            f"用户问题：{question}\n\n"
            f"可使用的表：{table_names}\n\n"
            f"请先生成 SQL，然后调用工具检查表结构确认无误，最后只输出 SQL。"
        )
        result = await Runner.run(self.agent, input=prompt)
        return clean_sql(result.final_output)

# 根据执行SQL如果失败修改SQL重新执行
class SQLExecuteAgent:
    def __init__(self, max_retry: int = 3):
        self.max_retry = max_retry
        self.rewrite_agent = Agent(
            name="SQL Rewriter",
            instructions=(
                "你是一个专业的 SQLite SQL 专家。用户的 SQL 执行失败了，"
                "请根据错误信息和用户原始问题，修正 SQL。\n"
                "要求：\n"
                "1. 只输出修正后的 SQL 语句，不要解释，不要 markdown 代码块\n"
                "2. 必须是 SELECT 语句\n"
                "3. 可以调用工具查看表结构、样例、外键来诊断问题"
            ),
            model="deepseek-flash",
            tools=[parse_table, parse_sample, list_relations],
        )

    async def run(self, question: str, sql: str):
        """
        返回 (success: bool, final_sql: str, result: list | None, err_msg: str | None)
        """
        for attempt in range(self.max_retry + 1):
            ok, err = parser.check_sql(sql)
            if ok:
                try:
                    result = parser.execute_sql(sql)
                    return True, sql, result, None
                except Exception as e:
                    err = traceback.format_exc()

            # 已经是最后一轮，不再修正
            if attempt >= self.max_retry:
                return False, sql, None, err

            print(f"⚠️ 第 {attempt + 1} 次 SQL 执行失败，尝试修正...")
            prompt = (
                f"用户原始问题：{question}\n\n"
                f"上次生成的 SQL：\n{sql}\n\n"
                f"执行报错信息：\n{err}\n\n"
                f"请修正 SQL，先调用工具核对结构，最后只输出 SQL。"
            )
            resp = await Runner.run(self.rewrite_agent, input=prompt)
            sql = clean_sql(resp.final_output)

        return False, sql, None, "max retry reached"

# 根据用户提问+SQL结果回答
class SQLResultSummaryAgent:
    def __init__(self):
        self.agent = Agent(
            name="Result Summarizer",
            instructions=(
                "你是一个数据分析师。请根据用户问题、执行的 SQL 和查询结果，"
                "用简洁的自然语言回答用户。\n"
                "要求：\n"
                "1. 答案必须基于 SQL 结果，不要编造\n"
                "2. 若结果是数字统计，直接给出数字\n"
                "3. 用与用户提问相同的语言作答\n"
                "4. 如果结果为空，说明'没有查到相关数据'"
            ),
            model="deepseek-flash",
        )

    async def run(self, question: str, sql: str, result: list) -> str:
        result_str = self._format_result(result)
        prompt = (
            f"用户问题：{question}\n\n"
            f"执行的 SQL：\n{sql}\n\n"
            f"SQL 查询结果：\n{result_str}\n\n"
            f"请回答用户问题。"
        )
        resp = await Runner.run(self.agent, input=prompt)
        return resp.final_output

    @staticmethod
    def _format_result(result: list, max_rows: int = 30) -> str:
        if not result:
            return "（空结果）"
        rows = [str(tuple(r)) for r in result]
        if len(rows) > max_rows:
            return f"（共 {len(rows)} 行，前 {max_rows} 行如下）\n" + "\n".join(rows[:max_rows])
        return "\n".join(rows)

class ChatBIPipeline:
    def __init__(self):
        self.select_agent  = SQLTableSelectAgent()
        self.gen_agent     = SQLGeneratorAgent()
        self.exec_agent    = SQLExecuteAgent()
        self.summary_agent = SQLResultSummaryAgent()

    async def run(self, question: str) -> dict:
        print(f"\n{'=' * 60}\n❓ 问题：{question}\n{'=' * 60}")

        # Step 1: 选表
        sel = await self.select_agent.run(question)
        table_names = self._extract_tables(sel.final_output)
        print(f"📌 选中表：{table_names}")

        # Step 2: 生成 SQL
        sql = await self.gen_agent.run(question, table_names)
        print(f"🧾 生成 SQL：{sql}")

        # Step 3: 执行 + 修正
        ok, final_sql, result, err = await self.exec_agent.run(question, sql)
        if not ok:
            print(f"❌ 执行失败：{err.splitlines()[-1] if err else 'unknown'}")
            return {
                "question": question,
                "tables": table_names,
                "sql": final_sql,
                "error": err,
                "answer": "抱歉，无法完成这次查询。",
            }
        print(f"✅ 执行成功，返回 {len(result)} 行")

        # Step 4: 总结
        answer = await self.summary_agent.run(question, final_sql, result)
        print(f"💬 回答：{answer}\n")

        return {
            "question": question,
            "tables": table_names,
            "sql": final_sql,
            "result": result,
            "answer": answer,
        }

    @staticmethod
    def _extract_tables(text: str) -> list[str]:
        """从 LLM 输出中提取合法表名，兜底用第一张表"""
        if not text:
            return [parser.table_names[0]]
        found = [t for t in parser.table_names if t in text]
        return found or [parser.table_names[0]]


async def main():
    pipeline = ChatBIPipeline()
    await pipeline.run("albums 表里一共有多少张专辑？")
    await pipeline.run("每个艺术家分别发行了多少张专辑？")

asyncio.run(main())