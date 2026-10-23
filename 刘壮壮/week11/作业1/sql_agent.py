"""
chinook.db 的基础 SQL Agent（仅 SQLite + DeepSeek）

1. 数据库解析
2. table 选择
3. sql 生成
4. sql 校验
5. sql 改写
6. sql 执行
7. 结果汇总
"""

import json
import os
import re
import sqlite3
from pathlib import Path

from openai import OpenAI

# https://api-docs.deepseek.com/zh-cn/
# base_url 用 OpenAI 兼容地址；model 用 deepseek-flash（当前 Flash 模型）
api_key = os.environ.get("DEEPSEEK_API_KEY")
base_url = "https://api.deepseek.com"
model = "deepseek-flash"

SYSTEM_TABLES = {"sqlite_sequence", "sqlite_stat1"}


class DBParser:
    """解析 SQLite 的表、字段、外键和一行样例。"""

    def __init__(self, db_path: str) -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        cur = self.conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        self.table_names = [
            row[0] for row in cur.fetchall() if row[0] not in SYSTEM_TABLES
        ]

        self.columns = {}
        self.foreign_keys = []
        self.samples = {}

        for table in self.table_names:
            cur.execute(f"PRAGMA table_info({table})")
            self.columns[table] = [
                {"name": row[1], "type": row[2], "pk": bool(row[5])}
                for row in cur.fetchall()
            ]

            cur.execute(f"PRAGMA foreign_key_list({table})")
            for row in cur.fetchall():
                self.foreign_keys.append(
                    f"{table}.{row[3]} -> {row[2]}.{row[4]}"
                )

            cur.execute(f"SELECT * FROM {table} LIMIT 1")
            sample = cur.fetchone()
            self.samples[table] = dict(sample) if sample else {}

        print("解析完成，表:", self.table_names)

    def schema_brief(self) -> str:
        lines = []
        for table in self.table_names:
            cols = ", ".join(
                f"{c['name']} {c['type']}{' PK' if c['pk'] else ''}"
                for c in self.columns[table]
            )
            lines.append(f"- {table}: {cols}")
        lines.append("外键: " + "; ".join(self.foreign_keys))
        return "\n".join(lines)

    def schema_detail(self, tables: list[str]) -> str:
        blocks = []
        for table in tables:
            cols = ", ".join(c["name"] for c in self.columns[table])
            blocks.append(f"表 {table} 字段: {cols}\n样例: {self.samples[table]}")
        fks = [
            fk
            for fk in self.foreign_keys
            if any(table in fk for table in tables)
        ]
        blocks.append("外键: " + "; ".join(fks))
        return "\n".join(blocks)

    def run_sql(self, sql: str):
        cur = self.conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description] if cur.description else []
        return columns, [dict(row) for row in rows]


class SQLAgent:
    """DeepSeek 驱动的 7 步 SQL 工作流。"""

    def __init__(self, parser: DBParser, max_retries: int = 2) -> None:
        self.parser = parser
        self.max_retries = max_retries
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def llm(self, prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return resp.choices[0].message.content or ""

    @staticmethod
    def extract_sql(text: str) -> str:
        match = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        text = text.strip()
        if text.upper().startswith("SELECT"):
            return text
        return ""

    def select_tables(self, question: str) -> list[str]:
        prompt = (
            "根据问题和 SQLite 表结构，选出回答问题需要的表（含 JOIN 中间表）。"
            "只输出 JSON 数组，例如 [\"tracks\", \"genres\"]。\n\n"
            f"{self.parser.schema_brief()}\n\n问题：{question}"
        )
        raw = self.llm(prompt)
        try:
            cleaned = re.sub(r"```json|```", "", raw).strip()
            tables = json.loads(cleaned)
            tables = [t for t in tables if t in self.parser.table_names]
            if tables:
                return tables
        except json.JSONDecodeError:
            pass
        return [t for t in self.parser.table_names if t in raw] or self.parser.table_names

    def generate_sql(self, question: str, tables: list[str]) -> str:
        prompt = (
            "根据下面的 SQLite 表结构写一条 SELECT。只输出 ```sql 代码块。"
            "字段值以样例为准（例如流派是英文 Rock，不是中文）。\n\n"
            f"{self.parser.schema_detail(tables)}\n\n问题：{question}"
        )
        return self.extract_sql(self.llm(prompt))

    def validate_sql(self, sql: str) -> tuple[bool, str]:
        if not sql.upper().startswith("SELECT"):
            return False, "只允许 SELECT"
        try:
            self.parser.conn.execute(f"EXPLAIN {sql}")
            return True, "ok"
        except sqlite3.Error as exc:
            return False, str(exc)

    def rewrite_sql(self, question: str, tables: list[str], sql: str, error: str) -> str:
        prompt = (
            "下面的 SQLite 语句执行失败，请改写成正确的 SELECT，只输出 ```sql 代码块。\n\n"
            f"问题：{question}\n"
            f"{self.parser.schema_detail(tables)}\n"
            f"原 SQL：{sql}\n错误：{error}"
        )
        return self.extract_sql(self.llm(prompt))

    def summarize(self, question: str, sql: str, rows: list[dict]) -> str:
        prompt = (
            "用中文简要回答问题，直接说结论。\n\n"
            f"问题：{question}\nSQL：{sql}\n结果：{rows[:20]}"
        )
        return self.llm(prompt)

    def run(self, question: str) -> dict:
        print("\n问题:", question)

        tables = self.select_tables(question)
        print("选表:", tables)

        sql = self.generate_sql(question, tables)
        print("生成 SQL:\n", sql)

        for i in range(self.max_retries + 1):
            ok, error = self.validate_sql(sql)
            if ok:
                print("校验通过")
                break
            print(f"校验失败: {error}")
            if i == self.max_retries:
                raise RuntimeError(error)
            sql = self.rewrite_sql(question, tables, sql, error)
            print("改写 SQL:\n", sql)

        columns, rows = self.parser.run_sql(sql)
        print(f"执行结果 {len(rows)} 行, 列: {columns}")
        for row in rows[:10]:
            print(row)

        summary = self.summarize(question, sql, rows)
        print("汇总:\n", summary)
        return {"tables": tables, "sql": sql, "rows": rows, "summary": summary}


if __name__ == "__main__":
    db_path = Path(__file__).resolve().parent / "chinook.db"
    parser = DBParser(str(db_path))
    agent = SQLAgent(parser)
    agent.run("销售额最高的前 5 位歌手是谁？各自卖了多少钱？")
