import os
from openai import OpenAI
from pathlib import Path
from db_parser import DBParser
import re
import time
import sqlite3
from typing import Any


class SQLAgent:
    """基于 SQLite / DeepSeek 的只读 SQL Agent。"""

    def __init__(self, db_path: str = "chinook.db"):
        # for backward compatibility, you can still use `https://api.deepseek.com/v1` as `base_url`.
        self.client = client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
        # 检查数据库路径
        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(f"数据库文件不存在：{self.db_path}")

        self.max_retries = 2
        self.max_rows = 50

        self.parser = DBParser(
            f"sqlite:///{self.db_path.as_posix()}"
        )
        self.table_names = self.parser.table_names

        # 通过只读 SQLite 连接执行查询。
        self.db_uri = self.db_path.as_uri() + "?mode=ro"

    def _ask_deepseek(self, prompt: str):
        result = self.client.chat.completions.create(
            model="deepseek-flash",
            messages=[{"role": "user", "content": prompt}]
        )
        try:
            return result.choices[0].message.content.strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"DeepSeek 返回格式异常：{result}"
            ) from exc

    @staticmethod
    def _clean_sql(text: str) -> str:
        """移除模型输出中的 Markdown SQL 代码围栏。"""
        text = text.strip()
        match = re.fullmatch(
            r"```(?:sql)?\s*(.*?)\s*```",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            text = match.group(1).strip()
        return text.rstrip(";").strip()

    def get_schema_context(self) -> dict[str, Any]:
        """提取所有表的字段信息、关系和少量样例。"""
        schemas = {}

        for table in self.table_names:
            fields = self.parser.get_table_fields(table)
            sample = self.parser.get_table_sample(table)

            schemas[table] = {
                "fields": fields.to_markdown(index=False),
                "sample": sample.head(3).to_markdown(index=False),
            }

        try:
            relations = self.parser.get_data_relations()
        except Exception:
            relations = "未能读取关系信息"

        return {
            "tables": schemas,
            "relations": str(relations),
        }

    def select_tables(
            self, question: str, schema: dict[str, Any]
    ) -> list[str]:
        """让模型选择表，只接受数据库中真实存在的表名。"""
        table_overview = "\n".join(
            f"- {name}: {info['fields']}"
            for name, info in schema["tables"].items()
        )

        prompt = f"""
    你是 SQLite 数据库分析专家。
    请根据用户问题，选择回答问题所必需的数据库表。

    数据库中的真实表和字段：
    {table_overview}

    表关系：
    {schema['relations']}

    用户问题：
    {question}

    规则：
    1. 只能选择上面出现的真实表名。
    2. 尽量选择最少但足够的表。
    3. 如果需要关联查询，选择关联链上的全部必要表。
    4. 只输出 JSON 数组，例如：
    ["Customers", "Invoices", "InvoiceLines"]
    5. 不要输出 Markdown 或其他解释。
    """
        raw = self._ask_deepseek(prompt)

        import json

        # 兼容模型偶尔添加的代码围栏。
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            selected = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"无法解析模型选择的表：{raw}"
            ) from exc

        if not isinstance(selected, list) or not selected:
            raise ValueError("模型没有选择有效的数据表")

        # 以数据库真实表名为准，防止模型虚构表。
        actual_names = {name.casefold(): name for name in self.table_names}
        result = []

        for name in selected:
            if not isinstance(name, str):
                continue
            actual = actual_names.get(name.casefold())
            if actual and actual not in result:
                result.append(actual)

        if not result:
            raise ValueError("所选表名均不存在于当前数据库")

        return result

    def generate_sql(
            self,
            question: str,
            tables: list[str],
            schema: dict[str, Any],
    ) -> str:
        context = {
            name: schema["tables"][name]
            for name in tables
        }

        prompt = f"""
    你是一个精确的 SQLite Text-to-SQL 专家。

    用户问题：
    {question}

    允许使用的表、字段与样例：
    {context}

    数据库表关系：
    {schema['relations']}

    生成规则：
    1. 只能查询允许使用的表和它们的真实字段。
    2. 使用 SQLite 语法。
    3. 只生成一条只读 SELECT 查询；允许使用 WITH CTE。
    4. 必要时根据外键关系进行 JOIN。
    5. 统计问题要正确处理 COUNT、SUM、AVG、GROUP BY 和排序。
    6. 不要臆造字段，不要猜测数据库中不存在的数据。
    7. 只输出 SQL，不要解释，不要使用 Markdown 代码围栏。
    """
        return self._clean_sql(self._ask_deepseek(prompt))

    def validate_sql(
            self, sql: str, tables: list[str]
    ) -> tuple[bool, str]:
        """校验SQL"""
        sql = sql.strip()
        if not sql:
            return False, "SQL 为空"

        # 先做快速入口检查，实际权限控制由 SQLite 完成。
        if not re.match(r"^(SELECT|WITH)\b", sql, re.IGNORECASE):
            return False, "只允许 SELECT 或 WITH 查询"

        # 不允许多语句，避免尾随其他 SQL。
        if ";" in sql.rstrip(";"):
            return False, "不允许多条 SQL 语句"

        try:
            flag, detail = self.parser.check_sql(sql)
            if not flag:
                return False, f"DBParser 检查未通过：{detail}"
        except Exception as exc:
            return False, f"DBParser 校验异常：{exc}"

        return True, "SQL 安全及语法检查通过"

    def rewrite_sql(
            self,
            question: str,
            old_sql: str,
            error: str,
            tables: list[str],
            schema: dict[str, Any],
    ) -> str:
        context = {
            name: schema["tables"][name]
            for name in tables
        }

        prompt = f"""
你是 SQLite SQL 修复专家。

用户问题：
{question}

允许使用的表和字段：
{context}

原始 SQL：
{old_sql}

校验错误：
{error}

请修复 SQL，使其正确回答用户问题。
只能使用允许的表及其字段，只能输出一条只读 SELECT/WITH 查询。
不得执行写入、删除、修改、DDL 或其他副作用操作。
只输出修复后的 SQL，不要解释，不要使用 Markdown 代码围栏。
"""
        return self._clean_sql(self._ask_deepseek(prompt))

    def execute_sql(self, sql: str, tables: list[str]):
        """只读连接执行 SQL，最多返回 max_rows 行。"""
        allowed = {name.casefold() for name in tables}

        # 简单增加默认结果行数限制。
        if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
            sql = sql.rstrip(";").strip()
            sql = f"SELECT * FROM ({sql}) AS _sql_agent_result LIMIT {self.max_rows}"

        with sqlite3.connect(self.db_uri, uri=True) as conn:
            cursor = conn.execute(sql)
            columns = [
                description[0] for description in cursor.description or []
            ]
            rows = cursor.fetchmany(self.max_rows)

        return {
            "columns": columns,
            "rows": [list(row) for row in rows],
            "row_count": len(rows),
            "truncated": len(rows) >= self.max_rows,
        }

    def summarize(
                self,
                question: str,
                sql: str,
                result: dict[str, Any],
        ) -> str:
            prompt = f"""
    你是一个严谨的数据分析助手。

    用户问题：
    {question}

    实际执行的 SQL：
    {sql}

    数据库实际返回的结果：
    {result}

    请用自然、简洁的中文回答用户问题。
    规则：
    1. 只根据真实查询结果作答，不得捏造数字。
    2. 如果结果为空，明确说明没有查到符合条件的数据。
    3. 如果结果被截断，说明当前只展示了部分结果。
    4. 如果结果包含多行，概括主要发现，并在必要时列出关键数值。
    5. 不要声称执行了 SQL 中不存在的统计或筛选。
    """
            return self._ask_deepseek(prompt)


    def run(self, question: str) -> dict[str, Any]:
        """依次执行解析、选表、生成、校验、修复、执行和汇总，并实时打印进度。"""
        started_at = time.perf_counter()
        stage = "检查输入"

        def log(message: str) -> None:
            elapsed = time.perf_counter() - started_at
            timestamp = time.strftime("%H:%M:%S")
            print(f"[{timestamp}] [SQLAgent] [+{elapsed:.2f}s] {message}", flush=True)

        try:
            if not question or not question.strip():
                raise ValueError("用户问题不能为空")

            log(f"开始处理问题：{question}")
            workflow = {
                "question": question,
                "tables": [],
                "sql": None,
                "result": None,
                "answer": None,
                "history": [],
            }

            stage = "数据库解析"
            log("[1/6] 开始读取数据库结构和样例")
            schema = self.get_schema_context()
            workflow["history"].append("数据库解析完成")
            log(f"[1/6] 数据库解析完成，共 {len(schema['tables'])} 张表")

            stage = "选择数据表"
            log("[2/6] 正在请求模型选择数据表")
            tables = self.select_tables(question, schema)
            workflow["tables"] = tables
            workflow["history"].append(f"已选择数据表：{tables}")
            log(f"[2/6] 已选择数据表：{tables}")

            stage = "生成 SQL"
            log("[3/6] 正在请求模型生成 SQL")
            sql = self.generate_sql(question, tables, schema)
            workflow["history"].append("SQL 生成完成")
            log(f"[3/6] SQL 生成完成：\n{sql}")

            for attempt in range(self.max_retries + 1):
                stage = "校验 SQL"
                log(f"[4/6] 开始第 {attempt + 1}/{self.max_retries + 1} 次 SQL 校验")
                ok, detail = self.validate_sql(sql, tables)
                if ok:
                    workflow["history"].append("SQL 校验通过")
                    log(f"[4/6] SQL 校验通过：{detail}")
                    break

                message = f"第 {attempt + 1} 次校验失败：{detail}"
                workflow["history"].append(message)
                log(f"[4/6] {message}")
                if attempt >= self.max_retries:
                    raise RuntimeError(
                        f"SQL 多次校验失败，停止执行。原因：{detail}"
                    )

                stage = "修复 SQL"
                log(f"[4/6] 正在请求模型修复 SQL（第 {attempt + 1}/{self.max_retries} 次修复）")
                sql = self.rewrite_sql(question, sql, detail, tables, schema)
                workflow["history"].append("已重新生成修复 SQL")
                log(f"[4/6] 修复 SQL 生成完成：\n{sql}")

            workflow["sql"] = sql
            stage = "执行 SQL"
            log("[5/6] 开始执行 SQL")
            result = self.execute_sql(sql, tables)
            workflow["result"] = result
            workflow["history"].append("SQL 执行完成")
            log(f"[5/6] SQL 执行完成，返回 {result['row_count']} 行，截断标记：{result['truncated']}")

            stage = "生成自然语言答案"
            log("[6/6] 正在请求模型汇总查询结果")
            answer = self.summarize(question, sql, result)
            workflow["answer"] = answer
            workflow["history"].append("自然语言答案生成完成")
            log("[6/6] 自然语言答案生成完成，全部流程结束")
            return workflow
        except Exception as exc:
            log(f"执行失败，当前阶段：{stage}；{type(exc).__name__}: {exc}")
            raise
