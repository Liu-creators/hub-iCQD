#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQL Agent —— 完整的 SQL 智能体工作流（参考 sql-agent.ipynb / code-agent.ipynb）

工作流步骤：
  1. 数据库解析   DBParser         —— 解析表结构 / 字段 / 外键 / 样例 / 统计信息
  2. 表选择       select_tables    —— 根据提问选择相关的数据表
  3. SQL 生成     generate_sql     —— 结合表结构生成 SQL
  4. SQL 校验     validate_sql     —— 编译校验（检查语法 / 表列引用，不执行）
  5. SQL 改写     rewrite_sql      —— 校验失败时结合报错信息改写 SQL
  6. SQL 执行     execute_sql      —— 真正执行 SQL 并返回结果
  7. 结果汇总     summarize        —— 将结果组织为自然语言回答


依赖: sqlalchemy>=2.0, pandas, openai

用法:
    export DEEPSEEK_API_KEY=你的key   # 先设置环境变量
    python sql_agent.py "每个客户的消费总额是多少？"
    DEEPSEEK_API_KEY=xxx DEEPSEEK_MODEL=deepseek-flash python sql_agent.py "每个流派有多少首歌？"
"""

import os
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import (
    MetaData,
    Table,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from openai import OpenAI

# ---------------------------------------------------------------------------
# LLM 配置（OpenAI 兼容接口，默认指向 DeepSeek）
# API Key 只从环境变量读取，绝不硬编码在源码里。
# ---------------------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")

# 数据库文件默认与本脚本放在同一目录下
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "chinook.db"


# ---------------------------------------------------------------------------
# 步骤 1：数据库解析
# ---------------------------------------------------------------------------
class DBParser:
    """解析数据库：表名、字段、主外键、统计信息与数据样例。

    db_url 支持：
        sqlite: sqlite:///./chinook.db
        mysql:  mysql://root:123456@localhost:3306/mydb?charset=utf8mb4
    """

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url
        if "sqlite" in db_url:
            self.db_type = "sqlite"
        elif "mysql" in db_url:
            self.db_type = "mysql"
        else:
            self.db_type = "unknown"

        self.engine = create_engine(db_url, echo=False)
        self.inspector = inspect(self.engine)
        # SQLAlchemy 的 get_table_names() 已经过滤掉 sqlite_sequence / sqlite_stat1 等内部表
        self.table_names: List[str] = self.inspector.get_table_names()

        self.foreign_keys: List[Dict[str, Any]] = []
        self._table_fields: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._table_sample: Dict[str, pd.DataFrame] = {}

        metadata = MetaData()
        # 只建立一次连接，逐表统计字段信息
        with self.engine.connect() as conn:
            for table_name in self.table_names:
                print("Table ->", table_name)

                # 累计外键
                for fk in self.inspector.get_foreign_keys(table_name):
                    self.foreign_keys.append(
                        {
                            "constrained_table": table_name,
                            "constrained_columns": fk["constrained_columns"],
                            "referred_table": fk["referred_table"],
                            "referred_columns": fk["referred_columns"],
                        }
                    )

                # 主键列（SQLAlchemy 2.0 的 get_columns 不再带 primary_key，需单独取）
                pk_columns = set()
                pk = self.inspector.get_pk_constraint(table_name)
                pk_columns.update(pk.get("constrained_columns", []))

                table_instance = Table(table_name, metadata, autoload_with=self.engine)
                table_columns = self.inspector.get_columns(table_name)

                fields: Dict[str, Dict[str, Any]] = {}
                for column_meta in table_columns:
                    name = column_meta["name"]
                    # SQLAlchemy 2.0 中通过下标访问列，不再支持 getattr(columns, name)
                    column_instance = table_instance.c[name]

                    info: Dict[str, Any] = {
                        "name": name,
                        "type": str(column_meta["type"]),
                        "nullable": column_meta.get("nullable", True),
                        "default": column_meta.get("default"),
                        "primary_key": name in pk_columns,
                    }

                    # distinct 取值个数
                    info["distinct"] = conn.execute(
                        select(func.count(func.distinct(column_instance))).select_from(table_instance)
                    ).scalar()

                    # 文本/字符字段统计众数（most frequent value）
                    col_type = str(column_meta["type"]).lower()
                    if any(k in col_type for k in ("text", "char", "varchar")):
                        info["mode"] = conn.execute(
                            select(column_instance, func.count().label("cnt"))
                            .select_from(table_instance)
                            .group_by(column_instance)
                            .order_by(func.count().desc())
                            .limit(1)
                        ).scalar()
                    else:
                        info["mode"] = None

                    # 空值个数
                    info["nan_count"] = conn.execute(
                        select(func.count()).select_from(table_instance).where(column_instance.is_(None))
                    ).scalar()

                    # max / min
                    info["max"] = conn.execute(select(func.max(column_instance)).select_from(table_instance)).scalar()
                    info["min"] = conn.execute(select(func.min(column_instance)).select_from(table_instance)).scalar()

                    # 任意取值（去重后取前 3 个，供大模型理解字段含义）
                    values = conn.execute(select(column_instance).select_from(table_instance).limit(10)).scalars().all()
                    info["random"] = list(dict.fromkeys(str(v) for v in values if v is not None))[:3]

                    fields[name] = info

                self._table_fields[table_name] = fields

                # 表样例（第一行）
                first_row = conn.execute(select(table_instance).limit(1)).first()
                df = pd.DataFrame([tuple(first_row)] if first_row else [], columns=[c["name"] for c in table_columns])
                self._table_sample[table_name] = df

    # ---------------------------- 查询辅助方法 ----------------------------
    def get_table_fields(self, table_name: str) -> pd.DataFrame:
        """获取表字段信息"""
        return pd.DataFrame.from_dict(self._table_fields[table_name]).T

    def get_data_relations(self) -> pd.DataFrame:
        """获取数据库链接信息（主键和外键）"""
        return pd.DataFrame(self.foreign_keys)

    def get_table_sample(self, table_name: str) -> pd.DataFrame:
        """获取数据表样例"""
        return self._table_sample[table_name]

    # ---------------------------- 供大模型使用的文本描述 ----------------------------
    def describe_relations(self) -> str:
        """外键关系描述，形如 invoices.CustomerId -> customers.CustomerId"""
        lines = []
        for fk in self.foreign_keys:
            for i, col in enumerate(fk["constrained_columns"]):
                referred = fk["referred_columns"][i] if i < len(fk["referred_columns"]) else "?"
                lines.append(f"{fk['constrained_table']}.{col} -> {fk['referred_table']}.{referred}")
        return "\n".join(lines)

    def describe_schema(self, tables: List[str], include_samples: bool = True) -> str:
        """生成某几张表的紧凑 schema 描述（供表选择 / SQL 生成使用）"""
        blocks = []
        for table_name in tables:
            if table_name not in self._table_fields:
                continue
            lines = [f"### 表 {table_name}"]
            for name, info in self._table_fields[table_name].items():
                flags = []
                if info["primary_key"]:
                    flags.append("主键")
                # 标注外键
                for fk in self.foreign_keys:
                    if fk["constrained_table"] == table_name and name in fk["constrained_columns"]:
                        referred = fk["referred_columns"][0]
                        flags.append(f"外键->{fk['referred_table']}.{referred}")
                        break
                suffix = (" " + ",".join(flags)) if flags else ""
                if include_samples and info.get("random"):
                    suffix += f" 示例值: {info['random']}"
                lines.append(f"- {name} ({info['type']}){suffix}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    # ---------------------------- SQL 编译校验 / 执行 ----------------------------
    def compile_check(self, sql: str) -> Tuple[bool, str]:
        """检查 SQL 是否“可编译”（语法 + 表/列引用合法），只编译、不执行。

        注意：这里校验的是“语法/结构正确”，不是“运行结果正确”：
          - 能捕获：语法错误、表/列不存在（prepare 阶段的 schema 解析）
          - 不真正执行：对 INSERT/UPDATE/DELETE 无副作用，对 SELECT 无查询开销
          - 局限：无法捕获运行时错误（如除零）和“结果是否真的正确”——
            前者在实际执行阶段处理，后者需要 ground truth 评测
        其他数据库（如 MySQL）没有等价的通用编译检查，退化为直接执行。

        返回: (是否通过编译校验, 报错信息)
        """
        statement = sql.strip().rstrip(";").strip()
        if self.db_type == "sqlite":
            statement = f"EXPLAIN {statement}"
        try:
            with self.engine.connect() as conn:
                conn.execute(text(statement))
            return True, "ok"
        except Exception:
            return False, traceback.format_exc()

    def execute_sql(self, sql: str) -> Tuple[List[str], List[tuple]]:
        """执行 SQL，返回 (列名列表, 行列表)"""
        with self.engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = [tuple(r) for r in result.fetchall()]
            return columns, rows


# ---------------------------------------------------------------------------
# SQL Agent：表选择 -> SQL 生成 -> 校验 -> 改写 -> 执行 -> 汇总
# ---------------------------------------------------------------------------
class SQLAgent:
    def __init__(
        self,
        db_url: str,
        api_key: str = DEEPSEEK_API_KEY,
        base_url: str = DEEPSEEK_BASE_URL,
        model: str = DEFAULT_MODEL,
        max_retry: int = 5,
    ) -> None:
        self.parser = DBParser(db_url)
        if not api_key:
            raise ValueError(
                "缺少 API Key：请先设置环境变量 DEEPSEEK_API_KEY（或传入 api_key 参数）。"
            )
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_retry = max_retry

        # 各类 prompt 模板
        self._table_select_prompt = """你是一个数据库专家。请根据用户提问，从下面的数据库中选择回答该问题所需的数据表（可以多选，也可以只选一张）。

数据库中的所有表名：{table_names}

表之间的外键关系：
{relations}

每张表的字段结构：
{schema}

用户提问：{question}

请直接输出所选择的表名，多个表名用英文逗号分隔，只输出表名，不要输出其他内容。"""

        self._sql_gen_prompt = """你是一个数据库专家。请根据用户提问和表结构，生成一条能在 SQLite 上直接执行的 SQL 语句。

用户提问：{question}

可用的表及其字段结构：
{schema}

表之间的外键关系：
{relations}

请直接输出 SQL 语句（不要用 markdown 代码块，不要输出任何解释）。"""

        self._sql_rewrite_prompt = """你是一个数据库专家。下面这条 SQL 校验/执行时报错，请结合报错信息修正后重新输出。

用户提问：{question}

表结构：
{schema}

出错的 SQL：
{sql}

报错信息：
{error}

请直接输出修正后的 SQL 语句（不要用 markdown 代码块，不要输出任何解释）。"""

        self._summary_prompt = """你是答案汇总专家。请把用户提问、执行的 SQL 和执行结果组织为自然语言回答。

用户提问：{question}

执行 SQL：{sql}

执行结果：
{result}

请直接输出自然语言回答。"""

    # ---------------------------- 大模型调用 ----------------------------
    def llm(self, messages: List[Dict[str, str]], temperature: float = 0.3) -> Optional[str]:
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"[LLM 调用失败] {e}")
            return None

    @staticmethod
    def _extract_sql(raw: Optional[str]) -> str:
        """从大模型输出中抽取纯 SQL（去掉 markdown 代码块 / 多余前缀）。"""
        if not raw:
            return ""
        raw = raw.strip()
        m = re.search(r"```(?:sql)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
        # 去掉类似 "sql\nSELECT ..." 的前缀
        raw = re.sub(r"^\s*sql\s*", "", raw, flags=re.IGNORECASE).strip()
        return raw

    # ---------------------------- 步骤 2：表选择 ----------------------------
    def select_tables(self, question: str) -> List[str]:
        table_names = ", ".join(self.parser.table_names)
        relations = self.parser.describe_relations()
        # 表选择阶段只给字段结构（不含样例），信息足够且更省 token
        schema = self.parser.describe_schema(self.parser.table_names, include_samples=False)

        prompt = self._table_select_prompt.format(
            table_names=table_names, relations=relations, schema=schema, question=question
        )
        raw = self.llm([{"role": "user", "content": prompt}], temperature=0.1)
        print(f"[表选择] 原始输出: {raw}")

        # 解析出合法的表名，非法输出回退为全部表
        selected = []
        if raw:
            for token in re.split(r"[,，\s]+", raw.strip()):
                token = token.strip("`'\"")
                if token in self.parser.table_names and token not in selected:
                    selected.append(token)
        if not selected:
            print("[表选择] 未解析出有效表名，回退为全部表")
            selected = list(self.parser.table_names)
        return selected

    # ---------------------------- 步骤 3：SQL 生成 ----------------------------
    def generate_sql(self, question: str, tables: List[str]) -> str:
        schema = self.parser.describe_schema(tables, include_samples=True)
        relations = self.parser.describe_relations()
        prompt = self._sql_gen_prompt.format(question=question, schema=schema, relations=relations)
        raw = self.llm([{"role": "user", "content": prompt}], temperature=0.1)
        sql = self._extract_sql(raw)
        print(f"[SQL 生成]\n{sql}")
        return sql

    # ---------------------------- 步骤 4：SQL 校验（只编译、不执行） ----------------------------
    def validate_sql(self, sql: str) -> Tuple[bool, str]:
        """校验 SQL 语法与表/列引用是否合法（编译期校验，不真正执行）。"""
        return self.parser.compile_check(sql)

    # ---------------------------- 步骤 5：SQL 改写 ----------------------------
    def rewrite_sql(self, question: str, sql: str, error: str) -> str:
        schema = self.parser.describe_schema(self.parser.table_names, include_samples=True)
        prompt = self._sql_rewrite_prompt.format(question=question, schema=schema, sql=sql, error=error)
        raw = self.llm([{"role": "user", "content": prompt}], temperature=0.1)
        new_sql = self._extract_sql(raw)
        print(f"[SQL 改写]\n{new_sql}")
        return new_sql

    # ---------------------------- 步骤 6：SQL 执行 ----------------------------
    def execute_sql(self, sql: str) -> Tuple[List[str], List[tuple]]:
        return self.parser.execute_sql(sql)

    # ---------------------------- 步骤 7：结果汇总 ----------------------------
    def summarize(self, question: str, sql: str, columns: List[str], rows: List[tuple]) -> str:
        result = self._format_result(columns, rows)
        prompt = self._summary_prompt.format(question=question, sql=sql, result=result)
        answer = self.llm([{"role": "user", "content": prompt}], temperature=0.6)
        return answer or ""

    @staticmethod
    def _format_result(columns: List[str], rows: List[tuple], max_rows: int = 200) -> str:
        if not rows:
            return "(无结果)"
        header = " | ".join(columns)
        body = [" | ".join("" if v is None else str(v) for v in row) for row in rows[:max_rows]]
        out = [header] + body
        if len(rows) > max_rows:
            out.append(f"... (共 {len(rows)} 行，仅展示前 {max_rows} 行)")
        return "\n".join(out)

    # ---------------------------- 入口：编排完整工作流 ----------------------------
    def action(self, question: str, verbose: bool = True) -> Dict[str, Any]:
        if verbose:
            print("=" * 60)
            print(f"提问: {question}")
            print("=" * 60)

        # 2. 表选择
        tables = self.select_tables(question)
        print(f"[表选择] -> {tables}")

        # 3. SQL 生成
        sql = self.generate_sql(question, tables)

        # 4-6. 校验（只编译）-> 改写 -> 执行（含运行时错误改写）循环
        columns: List[str] = []
        rows: List[tuple] = []
        validated = False
        for retry in range(self.max_retry):
            # 4. 校验：只编译不执行，捕获语法/表/列错误
            ok, err = self.validate_sql(sql)
            if not ok:
                print(f"[SQL 校验] 第 {retry + 1} 次编译失败，尝试改写")
                sql = self.rewrite_sql(question, sql, err)
                if not sql:
                    break
                continue

            # 6. 执行：真正运行（运行时错误也回退到改写）
            try:
                columns, rows = self.execute_sql(sql)
                validated = True
                print(f"[SQL 执行] 返回 {len(rows)} 行")
                break
            except Exception as e:
                print(f"[SQL 执行] 第 {retry + 1} 次运行时报错，尝试改写")
                sql = self.rewrite_sql(question, sql, str(e))
                if not sql:
                    break

        if not validated or not sql:
            print("[SQL Agent] 生成失败，无法得到可执行的 SQL")
            return {"question": question, "tables": tables, "sql": sql, "validated": False, "answer": ""}

        # 7. 结果汇总
        answer = self.summarize(question, sql, columns, rows)

        return {
            "question": question,
            "tables": tables,
            "sql": sql,
            "validated": validated,
            "columns": columns,
            "rows": rows,
            "answer": answer,
        }


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="SQL Agent 完整工作流（基于 chinook.db）")
    parser.add_argument("question", nargs="?", default="每个客户的消费总额是多少？", help="自然语言提问")
    parser.add_argument("--db", default=f"sqlite:///{DEFAULT_DB_PATH}", help="数据库连接地址")
    args = parser.parse_args()

    agent = SQLAgent(args.db)
    result = agent.action(args.question)

    print("\n" + "=" * 60)
    print("最终回答:")
    print("=" * 60)
    print(result["answer"] or "(未能生成回答)")
    print("\n执行 SQL:")
    print(result["sql"])
    print("\n表选择:", result["tables"])


if __name__ == "__main__":
    main()
