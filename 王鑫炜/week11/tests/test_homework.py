"""真实 Chinook + 注入模型响应；不使用真实密钥、不发外网请求。"""

import copy
import hashlib
import io
import json
import sqlite3
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError

from database import Database, PolicyError, QueryError
from llm import ChatModel, ModelError, ReplayModel, load_settings, parse_json_object
from main import ROOT, load_cases, main
from sql_agent import SQLAgent


CASES = {c["id"]: c for c in load_cases()}


class StubModel:
    mode = "test"

    def __init__(self, responses):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls = []

    def complete(self, stage, payload):
        self.calls.append((stage, payload))
        value = self.responses[stage].pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def selected(table="invoices"):
    return {"tables": [table], "reason": "统计发票", "needs_clarification": False, "clarification": ""}


def generated(sql):
    return {"sql": sql, "explanation": "使用真实查询结果"}


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(ROOT / "data" / "chinook.db")

    def test_schema_and_foreign_keys(self):
        schema = self.db.parse()
        self.assertEqual(len(schema), 11)
        self.assertEqual(schema["tracks"]["row_count"], 3503)
        self.assertEqual(schema["invoices"]["date_range"]["max"], "2013-12-22 00:00:00")
        self.assertIn({"column": "ArtistId", "target_table": "artists", "target_column": "ArtistId"},
                      schema["albums"]["foreign_keys"])
        email = next(c for c in schema["customers"]["columns"] if c["name"] == "Email")
        self.assertFalse(email["readable"])

    def test_join_bridge(self):
        result = self.db.expand_join_tables(["artists", "invoice_items"], self.db.parse())
        self.assertEqual(result, ["albums", "artists", "invoice_items", "tracks"])

    def test_missing_table_selection(self):
        with self.assertRaises(QueryError):
            self.db.expand_join_tables(["missing"], self.db.parse())

    def test_readonly_cte_and_literal_semicolon(self):
        sql = "WITH a AS (SELECT ArtistId FROM albums) SELECT COUNT(DISTINCT ArtistId), ';DROP TABLE albums' FROM a"
        self.db.validate(sql, ["albums"])
        self.assertEqual(self.db.execute(sql, ["albums"])["rows"], [[204, ";DROP TABLE albums"]])

    def test_dangerous_sql_is_rejected_without_mutation(self):
        before = hashlib.sha256(self.db.path.read_bytes()).hexdigest()
        attacks = [
            "DELETE FROM albums", "UPDATE albums SET Title='x'", "DROP TABLE albums",
            "INSERT INTO artists(Name) VALUES('x')", "CREATE TABLE hacked(x)",
            "ATTACH DATABASE ':memory:' AS other", "PRAGMA query_only=OFF",
            "SELECT load_extension('x')", "SELECT readfile('/etc/passwd')",
            "SELECT name FROM sqlite_master", "SELECT Email FROM customers",
            "SELECT Country FROM customers", "SELECT COUNT(*) FROM albums; DELETE FROM albums",
            "WITH a AS (SELECT Email FROM customers) SELECT * FROM a",
            "SELECT * FROM invoices", "SELECT randomblob(1000000000)",
        ]
        for sql in attacks:
            with self.subTest(sql=sql), self.assertRaises(QueryError):
                self.db.validate(sql, ["albums", "invoices"])
                # 部分 SQLite 版本在 EXPLAIN 阶段延后解析函数，执行层仍须拦截。
                self.db.execute(sql, ["albums", "invoices"])
        self.assertEqual(hashlib.sha256(self.db.path.read_bytes()).hexdigest(), before)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM albums", ["albums"])["rows"], [[347]])

    def test_execution_guard_without_prior_validation(self):
        with self.assertRaises(PolicyError):
            self.db.execute("DELETE FROM albums", ["albums"])

    def test_truncation_and_empty_results(self):
        db = Database(self.db.path, max_rows=2)
        result = db.execute("SELECT ArtistId FROM artists ORDER BY ArtistId", ["artists"])
        self.assertEqual(result["rows"], [[1], [2]])
        self.assertTrue(result["truncated"])
        empty = db.execute("SELECT ArtistId FROM artists WHERE ArtistId < 0", ["artists"])
        self.assertEqual(empty["rows"], [])
        self.assertFalse(empty["truncated"])

    def test_exact_limit_not_marked_truncated(self):
        db = Database(self.db.path, max_rows=2)
        self.assertFalse(db.execute("SELECT ArtistId FROM artists ORDER BY ArtistId LIMIT 2", ["artists"])["truncated"])

    def test_instruction_budget(self):
        db = Database(self.db.path, max_steps=1000)
        sql = "WITH RECURSIVE cnt(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM cnt WHERE x < 10000000) SELECT SUM(x) FROM cnt"
        with self.assertRaisesRegex(QueryError, "interrupted"):
            db.execute(sql, [])

    def test_invalid_column_and_multiple_statements(self):
        for sql in ("SELECT Amount FROM invoices", "SELECT 1; SELECT 2"):
            with self.subTest(sql=sql), self.assertRaises(QueryError):
                self.db.validate(sql, ["invoices"])

    def test_oversized_result(self):
        sql = "SELECT " + " || ".join(["'" + "a" * 1000 + "'" for _ in range(70)])
        with self.assertRaises(QueryError):
            self.db.execute(sql, [])

    def test_validation_does_not_execute_expression(self):
        # EXPLAIN 可通过，但真正求值时 ABS 的最小整数溢出。
        self.db.validate("SELECT ABS(-9223372036854775808)", [])
        with self.assertRaisesRegex(QueryError, "overflow"):
            self.db.execute("SELECT ABS(-9223372036854775808)", [])

    def test_missing_db_not_created(self):
        with TemporaryDirectory() as temp:
            missing = Path(temp) / "missing.db"
            with self.assertRaises(ValueError):
                Database(missing)
            self.assertFalse(missing.exists())

    def test_empty_user_table(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "empty.db"
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE example(id INTEGER PRIMARY KEY, value TEXT)")
            conn.close()
            self.assertEqual(Database(path).parse()["example"]["row_count"], 0)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(ROOT / "data" / "chinook.db")

    def test_all_replay_cases_on_real_database(self):
        for case in CASES.values():
            with self.subTest(case=case["id"]):
                out = SQLAgent(self.db, ReplayModel(case)).run(case["question"])
                expected_status = "needs_clarification" if case.get("needs_clarification") else "ok"
                self.assertEqual(out["status"], expected_status, out)
                if "expected_rows" in case:
                    self.assertEqual(out["result"]["rows"], case["expected_rows"])
                if case["id"] == "monthly_2013":
                    self.assertEqual(len(out["result"]["rows"]), 12)
                    self.assertEqual(out["result"]["rows"][0][0], "2013-01")
                if case["id"] == "genre_sales":
                    self.assertEqual(out["result"]["rows"][0], ["Rock", 835, 826.65])

    def test_rewrite_contains_database_error_and_schema(self):
        case = CASES["rewrite_column"]
        out = SQLAgent(self.db, ReplayModel(case)).run(case["question"])
        self.assertEqual(out["rewrites"], 1)
        self.assertEqual(out["result"]["rows"], [[2328.6]])
        stages = [e["stage"] for e in out["trace"]]
        self.assertIn("sql_rewrite", stages)
        self.assertEqual(stages.count("sql_validate"), 2)

    def test_execution_error_also_rewrites(self):
        model = StubModel({"select": [selected()],
                           "generate": [generated("SELECT ABS(-9223372036854775808) AS n")],
                           "rewrite": [generated("SELECT 42 AS n")],
                           "summarize": [{"answer": "n=42"}]})
        out = SQLAgent(self.db, model).run("执行错误后重试")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["rewrites"], 1)
        repair_payload = next(p for s, p in model.calls if s == "rewrite")
        self.assertIn("overflow", repair_payload["error"])
        self.assertIn("invoices", repair_payload["schema"])

    def test_rewrite_budget_exhaustion(self):
        bad = generated("SELECT missing FROM invoices")
        model = StubModel({"select": [selected()], "generate": [bad], "rewrite": [bad, bad]})
        out = SQLAgent(self.db, model, max_rewrites=2).run("销售额")
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["rewrites"], 2)
        self.assertIn("修正次数耗尽", out["error"])
        self.assertIsNone(out["result"])

    def test_policy_block_never_rewrites(self):
        model = StubModel({"select": [selected("customers")],
                           "generate": [generated("SELECT Email FROM customers")]})
        out = SQLAgent(self.db, model).run("导出客户邮箱")
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["rewrites"], 0)
        self.assertIsNone(out["result"])

    def test_summary_failure_preserves_data(self):
        model = StubModel({"select": [selected()],
                           "generate": [generated("SELECT COUNT(*) AS n FROM invoices")],
                           "summarize": [ModelError("模型 HTTP 请求失败，状态码 401")]})
        out = SQLAgent(self.db, model).run("发票数")
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["result"]["rows"], [[412]])

    def test_invalid_structure_corrected_once(self):
        model = StubModel({"select": [{"tables": "invoices"}, selected()],
                           "generate": [generated("SELECT COUNT(*) AS n FROM invoices")],
                           "summarize": [{"answer": "发票数为 412。"}]})
        out = SQLAgent(self.db, model).run("有多少发票")
        self.assertEqual(out["status"], "ok")
        self.assertIn("format_correction", model.calls[1][1])

    def test_invalid_structure_not_unbounded(self):
        model = StubModel({"select": [{"tables": []}, {"tables": []}]})
        self.assertEqual(SQLAgent(self.db, model).run("test")["status"], "error")
        self.assertEqual(len(model.calls), 2)

    def test_invalid_question(self):
        for question in ("", "   ", "a" * 4001, None):
            with self.subTest(question=str(question)[:20]), self.assertRaises(ValueError):
                SQLAgent(self.db, ReplayModel(CASES["artist_count"])).run(question)

    def test_corrupt_database_returns_structured_error(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "bad.db"
            path.write_text("not a database")
            out = SQLAgent(Database(path), ReplayModel(CASES["artist_count"])).run("test")
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["trace"][-1]["stage"], "database_parse")

    def test_replay_does_not_pretend_to_understand_new_question(self):
        model = ReplayModel(CASES["artist_count"])
        out = SQLAgent(self.db, model).run("一个任意新问题")
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["mode"], "replay")


class APIClientTests(unittest.TestCase):
    def settings(self):
        return {"OPENAI_API_KEY": "unit-test-placeholder", "OPENAI_MODEL": "test-model",
                "OPENAI_BASE_URL": "https://example.invalid/v1"}

    @staticmethod
    def envelope(obj):
        return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(obj, ensure_ascii=False)}}]}).encode())

    def test_json_parser_rejects_wrong_types(self):
        self.assertEqual(parse_json_object('```json\n{"answer":"好"}\n```'), {"answer": "好"})
        for content in ("[]", "文字", '{"value":NaN}', None):
            with self.subTest(content=content), self.assertRaises(ModelError):
                parse_json_object(content)

    def test_wire_payload_and_json_mode(self):
        settings = dict(self.settings(), OPENAI_JSON_MODE="true")
        model = ChatModel(settings)
        with patch.object(model.opener, "open", return_value=self.envelope({"answer": "42"})) as call:
            self.assertEqual(model.complete("summarize", {"question": "问题"}), {"answer": "42"})
        req = call.call_args.args[0]
        payload = json.loads(req.data)
        self.assertEqual(req.full_url, "https://example.invalid/v1/chat/completions")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual([m["role"] for m in payload["messages"]], ["system", "user"])
        self.assertIn("JSON", payload["messages"][0]["content"])
        self.assertEqual(req.get_header("Authorization"), "Bearer unit-test-placeholder")

    def test_full_workflow_through_real_client_parser(self):
        model = ChatModel(self.settings())
        replies = [selected(), generated("SELECT ROUND(SUM(Amount),2) AS revenue FROM invoices"),
                   generated("SELECT ROUND(SUM(Total),2) AS revenue FROM invoices"),
                   {"answer": "全部发票销售额为 2328.60，币种未注明。"}]
        with patch.object(model.opener, "open", side_effect=[self.envelope(r) for r in replies]) as call:
            out = SQLAgent(Database(ROOT / "data" / "chinook.db"), model).run("全部发票的总销售额是多少？")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["mode"], "live")  # transport 为测试替身，报告须明确并非真实模型验收。
        self.assertEqual(out["result"]["rows"], [[2328.6]])
        self.assertEqual(call.call_count, 4)

    def test_transient_http_retry(self):
        model = ChatModel(self.settings())
        http_error = HTTPError(model.url, 429, "rate", {}, io.BytesIO(b"private error"))
        with patch.object(model.opener, "open", side_effect=[http_error, self.envelope({"answer": "ok"})]) as call, \
                patch("llm.time.sleep"):
            self.assertEqual(model.complete("summarize", {"question": "q"})["answer"], "ok")
        self.assertEqual(call.call_count, 2)

    def test_auth_error_not_retried_or_leaked(self):
        model = ChatModel(self.settings())
        http_error = HTTPError(model.url, 401, "private secret", {}, io.BytesIO(b"private secret"))
        with patch.object(model.opener, "open", side_effect=http_error) as call:
            with self.assertRaisesRegex(ModelError, "401") as ctx:
                model.complete("select", {"question": "q"})
        self.assertNotIn("secret", str(ctx.exception))
        self.assertEqual(call.call_count, 1)

    def test_missing_settings_and_insecure_remote_url(self):
        for settings in ({}, dict(self.settings(), OPENAI_BASE_URL="http://example.com/v1")):
            with self.assertRaises(ModelError):
                ChatModel(settings)

    def test_environment_override(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / ".env"
            path.write_text("OPENAI_MODEL=file-model\nOPENAI_API_KEY=placeholder\n", encoding="utf-8")
            with patch.dict("os.environ", {"OPENAI_MODEL": "env-model"}, clear=True):
                self.assertEqual(load_settings(path)["OPENAI_MODEL"], "env-model")


class CLITests(unittest.TestCase):
    def test_demo_and_output_file(self):
        with TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            target = Path(temp) / "result.json"
            code = main(["--demo", "rewrite_column", "--output", str(target)])
            out = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(out["rewrites"], 1)

    def test_unknown_demo_nonzero(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--demo", "missing"]), 1)


if __name__ == "__main__":
    unittest.main()
