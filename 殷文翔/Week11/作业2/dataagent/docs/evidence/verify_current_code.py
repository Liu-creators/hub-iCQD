"""Offline checks of the two original modules; uses disposable databases only.

Run from the project root: python docs/evidence/verify_current_code.py
No model calls, API credentials, or changes to the original source are required.
"""

import ast
import contextlib
import gc
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import platform
import re
import sqlite3
import sys
import tempfile
from typing import Any

import pandas
import sqlalchemy
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True


def load_agent_class():
    source = ast.parse((ROOT / "sql_agent.py").read_text(encoding="utf-8-sig"))
    node = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "SQLAgent")
    namespace = {"Any": Any, "re": re, "sqlite3": sqlite3, "Path": Path}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "sql_agent.py", "exec"), namespace)
    return namespace["SQLAgent"]


def main():
    agent_class = load_agent_class()
    spec = importlib.util.spec_from_file_location("current_db_parser", ROOT / "db_parser.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observations = []

    def record(case, observed, expected):
        assert observed == expected, (case, observed, expected)
        observations.append({"case": case, "observed": observed, "expected_current_behavior": expected})

    with tempfile.TemporaryDirectory(prefix="dataagent-review-") as temp:
        db_path = Path(temp) / "fixture.db"
        with sqlite3.connect(db_path) as conn:
            conn.executescript("""
                CREATE TABLE allowed_table (id INTEGER PRIMARY KEY, value TEXT);
                CREATE TABLE restricted_table (secret TEXT);
                INSERT INTO restricted_table VALUES ('fixture-only-secret');
            """)
            conn.executemany("INSERT INTO allowed_table(value) VALUES (?)", [(str(i),) for i in range(50)])
        conn.close()

        parser = object.__new__(module.DBParser)
        parser.engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        parser.conn = parser.engine.connect()
        agent = object.__new__(agent_class)
        agent.parser = parser
        agent.db_uri = db_path.as_uri() + "?mode=ro"
        agent.max_rows = 50

        try:
            query = "WITH x AS (SELECT 1) UPDATE allowed_table SET value='changed' WHERE id=1"
            ok, _ = agent.validate_sql(query, ["allowed_table"])
            record("WITH_UPDATE_passes_validation", ok, True)
            value = parser.conn.execute(text("SELECT value FROM allowed_table WHERE id=1")).scalar_one()
            record("validation_changes_connection_visible_data", value, "changed")
            # Record visibility before rollback; this does not claim persistence after commit.
            parser.conn.rollback()

            query = "SELECT secret FROM restricted_table"
            ok, _ = agent.validate_sql(query, ["allowed_table"])
            record("unselected_table_passes_validation", ok, True)
            result = agent.execute_sql(query, ["allowed_table"])
            record("unselected_table_is_readable", result["rows"], [["fixture-only-secret"]])

            result = agent.execute_sql("SELECT id FROM allowed_table ORDER BY id", ["allowed_table"])
            record("exactly_50_rows_marked_truncated", result["truncated"], True)
            record("exactly_50_rows_returned", result["row_count"], 50)

            ok, _ = agent.validate_sql("SELECT ';' AS value", ["allowed_table"])
            record("semicolon_in_literal_passes_validation", ok, False)

            try:
                # LIMIT inside a literal bypasses the original regex wrapper,
                # ensuring rejection comes from read-only mode, not SQL syntax.
                agent.execute_sql("WITH x AS (SELECT 1) UPDATE allowed_table SET value='LIMIT' WHERE id=1", ["allowed_table"])
            except sqlite3.Error as exc:
                readonly_blocks_write = exc.sqlite_errorname == "SQLITE_READONLY"
            else:
                readonly_blocks_write = False
            record("execution_path_rejects_write", readonly_blocks_write, True)
        finally:
            parser.conn.close()
            parser.engine.dispose()

        empty_path = Path(temp) / "empty.db"
        with sqlite3.connect(empty_path) as conn:
            conn.execute("CREATE TABLE empty_text (label TEXT)")
        conn.close()
        stdout = io.StringIO()
        empty_parser = object.__new__(module.DBParser)
        empty_error = None
        try:
            with contextlib.redirect_stdout(stdout):
                empty_parser.__init__(f"sqlite:///{empty_path.as_posix()}")
        except Exception as exc:
            empty_error = type(exc).__name__
        finally:
            if hasattr(empty_parser, "conn"):
                empty_parser.conn.close()
            if hasattr(empty_parser, "engine"):
                empty_parser.engine.dispose()
        record("empty_text_table_initialization_error", empty_error, "TypeError")
        # Original execute_sql uses a transaction context, not an explicit close.
        # Collect any unreachable SQLite connection cycles before Windows cleanup.
        gc.collect()

    report = {
        "scope": "Original class methods; AST loading skips unavailable OpenAI import and __init__; temporary SQLite fixtures only.",
        "limitations": "No live LLM, target database, full run(), concurrency or production benchmark was tested.",
        "python_sqlite_version": sqlite3.sqlite_version,
        "python_version": platform.python_version(),
        "dependencies": {"sqlalchemy": sqlalchemy.__version__, "pandas": pandas.__version__},
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("sql_agent.py", "db_parser.py")},
        "checks_passed": len(observations),
        "observations": observations,
    }
    output = Path(__file__).with_name("current_code_observations.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
