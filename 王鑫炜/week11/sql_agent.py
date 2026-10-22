"""七步 SQL Agent workflow。模型负责语义，程序掌握状态和执行权限。"""

import sqlite3
import time

from database import ALLOWED_FUNCTIONS, PolicyError, QueryError
from llm import ModelError


class SQLAgent:
    def __init__(self, database, model, max_rewrites=2):
        if not 0 <= max_rewrites <= 5:
            raise ValueError("SQL 改写次数须在 0～5 内")
        self.database = database
        self.model = model
        self.max_rewrites = max_rewrites

    def _ask(self, stage, payload, check, trace):
        """格式错误最多纠正一次；这与 SQL 改写、HTTP 重试是三种不同预算。"""
        for attempt in range(2):
            try:
                obj = self.model.complete(stage, payload)
                check(obj)
                return obj
            except ModelError as exc:
                # 网络/认证错误由客户端处理，不再重复完整阶段。
                if not str(exc).startswith(("模型输出", "模型 JSON", "模型未返回", "字段")):
                    raise
                trace.append({"stage": stage, "status": "invalid_output", "error": str(exc)})
                if attempt:
                    raise
                payload = dict(payload, format_correction=str(exc) + "。请严格输出要求的 JSON 对象。")

    @staticmethod
    def _check_select(obj):
        if not isinstance(obj, dict):
            raise ModelError("字段：表选择须为对象")
        if (not isinstance(obj.get("tables"), list)
                or not all(isinstance(t, str) and t for t in obj["tables"])
                or type(obj.get("needs_clarification")) is not bool
                or not isinstance(obj.get("reason"), str)
                or not isinstance(obj.get("clarification"), str)):
            raise ModelError("字段：表选择 JSON 类型不符合要求")
        if obj["needs_clarification"] and not obj["clarification"].strip():
            raise ModelError("字段：需要澄清时必须给出具体追问")
        if not obj["needs_clarification"] and not obj["tables"]:
            raise ModelError("字段：不需要澄清时，表选择不能为空")

    @staticmethod
    def _check_sql(obj):
        if (not isinstance(obj, dict) or not isinstance(obj.get("sql"), str)
                or not obj["sql"].strip() or not isinstance(obj.get("explanation"), str)
                or not obj["explanation"].strip()):
            raise ModelError("字段：必须返回非空 sql 和 explanation 字符串")

    @staticmethod
    def _check_summary(obj):
        if not isinstance(obj, dict) or not isinstance(obj.get("answer"), str) or not obj["answer"].strip():
            raise ModelError("字段：必须返回非空 answer 字符串")

    def run(self, question):
        if not isinstance(question, str) or not question.strip() or len(question) > 4000:
            raise ValueError("问题必须为 1～4000 字符的非空文本")
        question = question.strip()
        started = time.monotonic()
        output = {"question": question, "mode": self.model.mode, "status": "error",
                  "selected_tables": [], "sql": None, "result": None, "answer": "",
                  "rewrites": 0, "trace": []}
        trace = output["trace"]
        stage = "database_parse"
        try:
            schema = self.database.parse()
            trace.append({"stage": stage, "status": "ok", "table_count": len(schema)})
            stage = "table_select"
            catalog = {t: {"description": x["description"],
                            "columns": [c["name"] for c in x["columns"] if c["readable"]],
                            "date_range": x.get("date_range")}
                       for t, x in schema.items()}
            selection = self._ask("select", {"question": question, "catalog": catalog},
                                  self._check_select, trace)
            if selection["needs_clarification"]:
                output.update(status="needs_clarification", answer=selection["clarification"])
                trace.append({"stage": stage, "status": "needs_clarification"})
                return output
            tables = self.database.expand_join_tables(selection["tables"], schema)
            output["selected_tables"] = tables
            trace.append({"stage": stage, "status": "ok", "requested_tables": selection["tables"],
                          "tables": tables, "reason": selection["reason"]})
            payload = {"question": question, "schema": {t: schema[t] for t in tables},
                       "allowed_functions": sorted(ALLOWED_FUNCTIONS)}
            stage = "sql_generate"
            generated = self._ask("generate", payload, self._check_sql, trace)
            trace.append({"stage": stage, "status": "ok", **generated})
            while True:
                output["sql"] = generated["sql"]
                output["explanation"] = generated["explanation"]
                try:
                    stage = "sql_validate"
                    validation = self.database.validate(generated["sql"], tables)
                    trace.append({"stage": stage, "status": "ok", "plan": validation["plan"]})
                    stage = "sql_execute"
                    result = self.database.execute(generated["sql"], tables)
                    trace.append({"stage": stage, "status": "ok",
                                  "returned_rows": result["returned_rows"], "truncated": result["truncated"]})
                    output["result"] = result
                    break
                except PolicyError:
                    # 权限错误直接停止，不能让模型重写后绕过限制。
                    raise
                except QueryError as exc:
                    trace.append({"stage": stage, "status": "error", "error": str(exc),
                                  "sql": generated["sql"]})
                    if output["rewrites"] >= self.max_rewrites:
                        raise QueryError("SQL 修正次数耗尽：" + str(exc)) from exc
                    stage = "sql_rewrite"
                    generated = self._ask("rewrite", dict(payload, sql=generated["sql"], error=str(exc)),
                                          self._check_sql, trace)
                    output["rewrites"] += 1
                    trace.append({"stage": stage, "status": "ok", **generated})
            stage = "result_summary"
            try:
                summary = self._ask("summarize", {"question": question, "sql": output["sql"],
                                    "explanation": output["explanation"], "result": output["result"]},
                                    self._check_summary, trace)
                output.update(status="ok", answer=summary["answer"])
                trace.append({"stage": stage, "status": "ok"})
            except ModelError as exc:
                # SQL 已成功时保留真实结果，但不把总结失败伪装成完整成功。
                output.update(status="partial", answer="查询已完成，模型总结失败，请查看 result 中的真实数据。",
                              error=str(exc))
                trace.append({"stage": stage, "status": "error", "error": str(exc)})
        except (QueryError, ModelError, sqlite3.Error, sqlite3.Warning) as exc:
            output.update(status="blocked" if isinstance(exc, PolicyError) else "error", error=str(exc))
            trace.append({"stage": stage, "status": output["status"], "error": str(exc)})
        finally:
            output["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
        return output
