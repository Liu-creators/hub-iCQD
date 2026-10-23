"""Chinook SQL Agent：数据库解析、模型编排、只读执行与命令行入口。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote


# OpenAI-compatible API configuration
os.environ["OPENAI_API_KEY"] = "sk-bf424083topabu4e6b33dacd6be11"
os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE = BASE_DIR.parent / "04_SQL-Code-Agent-Demo" / "chinook.db"
RESULT_LIMIT = 100
REPAIR_LIMIT = 2


@dataclass
class TableSchema:
    name: str
    columns: list[dict[str, Any]]
    foreign_keys: list[dict[str, Any]]


@dataclass
class QueryOutput:
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool


class TextModel(Protocol):
    def respond(self, system: str, prompt: str) -> str: ...


class ModelClient:
    """OpenAI-compatible chat API adapter; credentials come from environment."""

    def __init__(self) -> None:
        from openai import OpenAI

        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("请设置 OPENAI_API_KEY 环境变量")
        self.model = os.getenv("OPENAI_MODEL", "deepseek-flash")
        self.client = OpenAI(
            api_key=key,
            base_url=os.getenv(
                "OPENAI_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )

    def respond(self, system: str, prompt: str) -> str:
        result = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        )
        answer = result.choices[0].message.content
        if not answer:
            raise RuntimeError("模型没有返回文本")
        return answer.strip()


class DatabaseCatalog:
    """只缓存数据库结构；字段画像按需扩展，避免启动时逐字段扫描全库。"""

    def __init__(self, path: str | Path = DEFAULT_DATABASE) -> None:
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"找不到 SQLite 文件：{self.path}")
        self.schemas = self._load_schemas()

    def connect(self) -> sqlite3.Connection:
        uri = quote(self.path.as_posix(), safe="/:")
        connection = sqlite3.connect(f"file:{uri}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    def _load_schemas(self) -> dict[str, TableSchema]:
        schemas: dict[str, TableSchema] = {}
        with closing(self.connect()) as db:
            names = db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for (name,) in names:
                escaped = '"' + name.replace('"', '""') + '"'
                columns = [dict(row) for row in db.execute(f"PRAGMA table_info({escaped})")]
                foreign_keys = [dict(row) for row in db.execute(f"PRAGMA foreign_key_list({escaped})")]
                schemas[name] = TableSchema(name, columns, foreign_keys)
        return schemas

    @property
    def table_names(self) -> list[str]:
        return list(self.schemas)

    def catalog_text(self) -> str:
        lines = []
        for schema in self.schemas.values():
            column_names = ", ".join(col["name"] for col in schema.columns)
            lines.append(f"{schema.name}: {column_names}")
            for fk in schema.foreign_keys:
                lines.append(f"  joins {schema.name}.{fk['from']} → {fk['table']}.{fk['to']}")
        return "\n".join(lines)

    def schema_text(self, tables: list[str]) -> str:
        return "\n".join(
            json.dumps(asdict(self.schemas[name]), ensure_ascii=False, default=str)
            for name in tables
        )


def parse_json(text: str) -> dict[str, Any]:
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text, flags=re.I)
    left, right = text.find("{"), text.rfind("}")
    if left < 0 or right < left:
        raise ValueError("模型输出中没有 JSON 对象")
    value = json.loads(text[left : right + 1])
    if not isinstance(value, dict):
        raise ValueError("模型输出必须是 JSON 对象")
    return value


def clean_sql(text: str) -> str:
    text = re.sub(r"^\s*```(?:sql)?\s*|\s*```\s*$", "", text, flags=re.I).strip()
    return re.sub(r";\s*$", "", text)


class ReadOnlyQueryRunner:
    """SQLite authorizer enforces read-only access and table-level allowlisting."""

    DENIED = {
        getattr(sqlite3, name)
        for name in (
            "SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE", "SQLITE_CREATE_INDEX",
            "SQLITE_CREATE_TABLE", "SQLITE_CREATE_TRIGGER", "SQLITE_CREATE_VIEW",
            "SQLITE_CREATE_TEMP_INDEX", "SQLITE_CREATE_TEMP_TABLE", "SQLITE_CREATE_TEMP_TRIGGER",
            "SQLITE_CREATE_TEMP_VIEW", "SQLITE_DROP_INDEX", "SQLITE_DROP_TABLE", "SQLITE_DROP_TRIGGER",
            "SQLITE_DROP_VIEW", "SQLITE_DROP_TEMP_INDEX", "SQLITE_DROP_TEMP_TABLE",
            "SQLITE_DROP_TEMP_TRIGGER", "SQLITE_DROP_TEMP_VIEW", "SQLITE_ALTER_TABLE",
            "SQLITE_ATTACH", "SQLITE_DETACH", "SQLITE_PRAGMA", "SQLITE_TRANSACTION",
            "SQLITE_SAVEPOINT", "SQLITE_CREATE_VTABLE", "SQLITE_DROP_VTABLE",
        )
        if hasattr(sqlite3, name)
    }

    def __init__(self, catalog: DatabaseCatalog, row_limit: int = RESULT_LIMIT) -> None:
        self.catalog = catalog
        self.row_limit = row_limit

    def _guard(self, tables: set[str]) -> sqlite3.Connection:
        db = self.catalog.connect()

        def authorize(action: int, arg1: str | None, _arg2: str | None,
                      _database: str | None, _source: str | None) -> int:
            if action in self.DENIED:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_READ and arg1:
                if arg1.startswith("sqlite_") or arg1 not in tables:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        db.set_authorizer(authorize)
        db.set_progress_handler(lambda: 1, 5_000_000)
        return db

    @staticmethod
    def _read_statement(sql: str) -> str:
        sql = clean_sql(sql)
        # Drop leading comments before applying the first-token check.
        while True:
            trimmed = re.sub(r"^\s*(?:--[^\n]*(?:\n|$)|/\*.*?\*/\s*)", "", sql, count=1, flags=re.S)
            if trimmed == sql:
                break
            sql = trimmed
        if not re.match(r"^(SELECT|WITH)\b", sql, flags=re.I):
            raise ValueError("只支持 SELECT 或 WITH 查询")
        return sql

    def validate(self, sql: str, tables: set[str]) -> tuple[bool, str]:
        try:
            statement = self._read_statement(sql)
            with closing(self._guard(tables)) as db:
                db.execute(f"EXPLAIN QUERY PLAN {statement}").fetchall()
            return True, "ok"
        except Exception as error:
            return False, f"{type(error).__name__}: {error}"

    def execute(self, sql: str, tables: set[str]) -> QueryOutput:
        statement = self._read_statement(sql)
        with closing(self._guard(tables)) as db:
            cursor = db.execute(statement)
            columns = [col[0] for col in cursor.description or []]
            values = cursor.fetchmany(self.row_limit + 1)
        truncated = len(values) > self.row_limit
        values = values[: self.row_limit]
        return QueryOutput(columns, [dict(row) for row in values], truncated)


class SQLAgentWorkflow:
    """Coordinates model decisions while keeping all database access in Python."""

    def __init__(self, catalog: DatabaseCatalog, model: TextModel,
                 max_repairs: int = REPAIR_LIMIT, row_limit: int = RESULT_LIMIT) -> None:
        self.catalog = catalog
        self.model = model
        self.max_repairs = max_repairs
        self.runner = ReadOnlyQueryRunner(catalog, row_limit)

    def choose_tables(self, question: str) -> tuple[list[str], str]:
        raw = self.model.respond(
            "从数据库目录中挑选回答问题所需的表。返回 JSON："
            '{"tables":["表名"],"reason":"选择理由"}。不要编造表名。',
            f"问题：{question}\n数据库目录：\n{self.catalog.catalog_text()}",
        )
        data = parse_json(raw)
        selected = data.get("tables")
        if not isinstance(selected, list) or not selected:
            raise ValueError("选表结果必须包含非空 tables 列表")
        invalid = [name for name in selected if not isinstance(name, str) or name not in self.catalog.schemas]
        if invalid:
            raise ValueError(f"选表结果包含无效表名：{invalid}")
        return list(dict.fromkeys(selected)), str(data.get("reason", ""))

    def draft_sql(self, question: str, tables: list[str], reason: str) -> str:
        raw = self.model.respond(
            "你是 SQLite 查询生成器。只生成只读查询。返回 JSON："
            '{"sql":"SQL语句","note":"必要时简述口径"}。',
            f"问题：{question}\n选表理由：{reason}\nSchema：\n"
            f"{self.catalog.schema_text(tables)}\n只使用这些表和字段；明细结果限制在 100 行。",
        )
        sql = parse_json(raw).get("sql")
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("SQL 生成结果为空")
        return clean_sql(sql)

    def repair_sql(self, question: str, sql: str, error: str, tables: list[str]) -> str:
        raw = self.model.respond(
            "修复 SQLite 查询。保留用户问题的含义，只返回 JSON：{\"sql\":\"修复后的 SQL\"}。",
            f"问题：{question}\n可用 schema：\n{self.catalog.schema_text(tables)}\n"
            f"失败 SQL：\n{sql}\n数据库反馈：\n{error}",
        )
        repaired = parse_json(raw).get("sql")
        if not isinstance(repaired, str) or not repaired.strip():
            raise ValueError("SQL 改写结果为空")
        return clean_sql(repaired)

    def summarize(self, question: str, sql: str, output: QueryOutput) -> str:
        return self.model.respond(
            "用中文回答用户。结论和数字必须能从查询结果中找到；如果结果被截断，要说明。",
            f"问题：{question}\nSQL：{sql}\n结果：\n"
            f"{json.dumps(asdict(output), ensure_ascii=False, default=str)}",
        )

    def run(self, question: str) -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise ValueError("问题不能为空")

        tables, reason = self.choose_tables(question)
        allowed = set(tables)
        sql = self.draft_sql(question, tables, reason)
        last_error = ""

        for repair_count in range(self.max_repairs + 1):
            valid, message = self.runner.validate(sql, allowed)
            if valid:
                try:
                    output = self.runner.execute(sql, allowed)
                    return {
                        "question": question,
                        "tables": tables,
                        "sql": sql,
                        "result": asdict(output),
                        "answer": self.summarize(question, sql, output),
                        "repair_count": repair_count,
                    }
                except Exception as error:
                    message = f"{type(error).__name__}: {error}"
            last_error = message
            if repair_count < self.max_repairs:
                sql = self.repair_sql(question, sql, last_error, tables)

        raise RuntimeError(f"SQL 修复 {self.max_repairs} 次后仍失败：{last_error}")


def main() -> int:
    """CLI: 本地查看 schema，或向 Chinook 数据库提交自然语言问题。"""
    cli = argparse.ArgumentParser(description="向 Chinook 数据库提问")
    cli.add_argument("question", nargs="?", help="自然语言问题")
    cli.add_argument("--db", default=str(DEFAULT_DATABASE), help="SQLite 文件路径")
    cli.add_argument("--tables", action="store_true", help="查看数据库表及字段")
    cli.add_argument("--describe", metavar="TABLE", help="查看一张表的字段和外键")
    args = cli.parse_args()

    catalog = DatabaseCatalog(args.db)
    if args.tables:
        print(catalog.catalog_text())
        return 0
    if args.describe:
        if args.describe not in catalog.schemas:
            cli.error(f"未知表名：{args.describe}")
        print(catalog.schema_text([args.describe]))
        return 0

    model = ModelClient()
    workflow = SQLAgentWorkflow(catalog, model)
    if args.question:
        print(json.dumps(workflow.run(args.question), ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"已加载 {len(catalog.table_names)} 张表。输入 exit 结束。")
    while True:
        try:
            question = input("问题> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if question.lower() in {"exit", "quit", "q"}:
            break
        if question:
            try:
                result = workflow.run(question)
                print(f"回答：{result['answer']}\nSQL：{result['sql']}\n")
            except Exception as error:
                print(f"处理失败：{error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
