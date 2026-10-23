#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Week11 作业一：基于 chinook.db 的 SQL Agent 完整工作流。

工作流（参考 04_SQL-Code-Agent-Demo/sql-agent.ipynb）：
    1. 数据库解析  DatabaseParser.profile_all      表/字段/类型/唯一值/空值/极值/众数/样例/主外键
    2. 表选择      SQLAgent.select_tables          LLM 依据问题 + 表清单挑选必要表
    3. SQL 生成    SQLAgent.generate_sql           依据选中表的结构生成 SQL
    4. SQL 校验    SQLAgent.validate_sql           静态规则 + EXPLAIN 预编译（不真正执行）
    5. SQL 改写    SQLAgent.rewrite_sql            依据校验报错自动重写，最多 max_rewrite 次
    6. SQL 执行    DatabaseParser.execute_sql      自动补 LIMIT，返回 DataFrame
    7. 结果汇总    SQLAgent.summarize              SQL + 结果 -> 自然语言结论

用法：
    python 作业一.py                                  # 交互式问答
    python 作业一.py "你的问题"                        # 单条提问
    python 作业一.py --tables                         # 看库里有哪些表、字段（不调 LLM）
    python 作业一.py --describe tracks                # 看某张表的字段画像与样例
    python 作业一.py --selftest                       # 不调用 LLM，自检解析/校验/执行

LLM 配置（默认使用 DeepSeek Flash）：
    DEEPSEEK_API_KEY=xxx                  # DeepSeek API Key
    SQL_AGENT_LLM=deepseek                # 可省略，默认 deepseek
    SQL_AGENT_BASE_URL=...                # 可选，默认 https://api.deepseek.com
    SQL_AGENT_MODEL=...                   # 可选，默认 deepseek-flash
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import requests
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy import types as sqltypes


# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

DEFAULT_DB = Path(__file__).resolve().with_name("chinook.db")
DEFAULT_LIMIT = 100
DEFAULT_MAX_REWRITE = 2
MAX_TABLES = 12
SYSTEM_TABLE_PREFIXES = ("sqlite_",)

# 禁止出现的关键字（写操作 / DDL / 运维命令）
FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|attach|detach|"
    r"pragma|vacuum|grant|revoke|transaction|commit|rollback)\b",
    re.IGNORECASE,
)
SQL_BLOCK = re.compile(r"```(?:sql|SQL)?\s*(.*?)```", re.DOTALL)


# --------------------------------------------------------------------------- #
# 1. 数据库解析
# --------------------------------------------------------------------------- #


@dataclass
class ColumnProfile:
    """单个字段的画像信息。"""

    name: str
    dtype: str
    nullable: bool = True
    primary_key: bool = False
    distinct: Optional[int] = None
    nan_count: Optional[int] = None
    min_value: Any = None
    max_value: Any = None
    mode: Any = None
    samples: List[str] = field(default_factory=list)

    def describe(self) -> str:
        """渲染成单行描述，供 prompt 使用。"""
        meta: List[str] = []
        if self.primary_key:
            meta.append("PK")
        if self.distinct is not None:
            meta.append(f"唯一值={self.distinct}")
        if self.nan_count:
            meta.append(f"空值={self.nan_count}")
        if self.min_value is not None or self.max_value is not None:
            meta.append(f"范围=[{self.min_value}, {self.max_value}]")
        if self.mode is not None:
            meta.append(f"众数={self.mode}")
        if self.samples:
            meta.append("样例=" + " / ".join(self.samples))
        suffix = f"（{'; '.join(meta)}）" if meta else ""
        return f"  - {self.name} {self.dtype}{suffix}"


def _is_comparable(dtype: str) -> bool:
    """数值 / 日期类型才统计 min、max。"""
    lowered = dtype.lower()
    keys = ("int", "real", "num", "float", "double", "dec", "date", "time")
    return any(k in lowered for k in keys)


def _is_textual(dtype: str) -> bool:
    lowered = dtype.lower()
    return "char" in lowered or "text" in lowered or "clob" in lowered


def _normalize_scalar(value: Any) -> Any:
    """把 1.0 这类整数值浮点数转成 int，让 schema 描述更易读。"""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _type_flags(dtype_obj: Any, dtype_text: str) -> Tuple[bool, bool]:
    """返回 (是否统计 min/max, 是否文本)。

    优先用 SQLAlchemy 类型对象判断（跨方言有效），未知类型再回退到类型名匹配。
    """
    numeric = (
        sqltypes.Integer,
        sqltypes.Numeric,
        sqltypes.Float,
        sqltypes.Boolean,
        sqltypes.Date,
        sqltypes.DateTime,
        sqltypes.Time,
        sqltypes.Interval,
    )
    textual = (sqltypes.String, sqltypes.Text)
    if isinstance(dtype_obj, textual):
        return False, True
    if isinstance(dtype_obj, numeric):
        return True, False
    return _is_comparable(dtype_text), _is_textual(dtype_text)


class DatabaseParser:
    """数据库解析器：读取元数据 + 统计字段画像 + 生成 prompt 用的 schema 文本。"""

    def __init__(
        self,
        db_url: str,
        *,
        sample_size: int = 3,
        profiling: bool = True,
        verbose: bool = True,
    ) -> None:
        """
        Parameters
        ----------
        db_url:
            数据库连接串，例如 ``sqlite:///chinook.db``、
            ``mysql://root:123456@localhost:3306/mydb?charset=utf8mb4``
        """
        self.db_url = db_url
        self.engine = create_engine(db_url, echo=False)
        # 方言名交给 SQLAlchemy 判断（sqlite / mysql / postgresql / oracle ...），不靠字符串猜
        self.db_type = self.engine.dialect.name
        self.inspector = inspect(self.engine)

        # 过滤 sqlite_sequence / sqlite_stat1 这类系统表
        self.table_names: List[str] = sorted(
            name
            for name in self.inspector.get_table_names()
            if not name.startswith(SYSTEM_TABLE_PREFIXES)
        )

        self.columns: Dict[str, Dict[str, ColumnProfile]] = {}
        self.primary_keys: Dict[str, List[str]] = {}
        self.foreign_keys: List[Dict[str, Any]] = []
        self.row_counts: Dict[str, int] = {}

        self.sample_size = sample_size
        self.verbose = verbose

        if profiling:
            self.profile_all()

    # ---------------------------- 基础工具 ---------------------------- #

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message, flush=True)

    def _table(self, table_name: str) -> Table:
        return Table(table_name, MetaData(), autoload_with=self.engine)

    def quote(self, identifier: str) -> str:
        """按当前方言给标识符加引号（表名含空格 / 保留字时必需）。"""
        return self.engine.dialect.identifier_preparer.quote(identifier)

    @staticmethod
    def _to_frame(result) -> pd.DataFrame:  # noqa: ANN001 - SQLAlchemy Result
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    # ---------------------------- 画像统计 ---------------------------- #

    def profile_all(self) -> None:
        """逐表统计字段信息（唯一值、空值、极值、众数、样例）。"""
        self._log(f"[1] 数据库解析：{self.db_type} / 共 {len(self.table_names)} 张表")
        for index, table_name in enumerate(self.table_names, start=1):
            self.profile_table(table_name)
            if self.verbose:
                count = len(self.columns.get(table_name, {}))
                rows = self.row_counts.get(table_name, 0)
                print(f"    ({index}/{len(self.table_names)}) {table_name}: "
                      f"{rows} 行 / {count} 字段", flush=True)

    def profile_table(self, table_name: str) -> None:
        """统计单张表的字段画像、主键与外键。"""
        table = self._table(table_name)
        pk_columns = list(self.inspector.get_pk_constraint(table_name).get("constrained_columns") or [])
        self.primary_keys[table_name] = pk_columns

        for fk in self.inspector.get_foreign_keys(table_name):
            self.foreign_keys.append(
                {
                    "constrained_table": table_name,
                    "constrained_columns": list(fk.get("constrained_columns") or []),
                    "referred_table": fk.get("referred_table"),
                    "referred_columns": list(fk.get("referred_columns") or []),
                }
            )

        profiles: Dict[str, ColumnProfile] = {}
        with self.engine.connect() as conn:
            self.row_counts[table_name] = int(
                conn.execute(select(func.count()).select_from(table)).scalar() or 0
            )

            for column_meta in self.inspector.get_columns(table_name):
                name = column_meta["name"]
                column = table.columns[name]
                profile = ColumnProfile(
                    name=name,
                    dtype=str(column_meta["type"]),
                    nullable=bool(column_meta.get("nullable", True)),
                    primary_key=name in pk_columns,
                )
                comparable, textual = _type_flags(column_meta["type"], profile.dtype)

                try:
                    profile.distinct = conn.execute(
                        select(func.count(func.distinct(column)))
                    ).scalar()
                    profile.nan_count = conn.execute(
                        select(func.count()).select_from(table).where(column.is_(None))
                    ).scalar()
                except Exception:  # noqa: BLE001 - 个别字段统计失败不影响整体
                    pass

                if comparable:
                    try:
                        profile.min_value, profile.max_value = conn.execute(
                            select(func.min(column), func.max(column))
                        ).one()
                        profile.min_value = _normalize_scalar(profile.min_value)
                        profile.max_value = _normalize_scalar(profile.max_value)
                    except Exception:  # noqa: BLE001
                        pass

                if textual:
                    try:
                        top = conn.execute(
                            select(column, func.count().label("cnt"))
                            .where(column.is_not(None))
                            .group_by(column)
                            .order_by(func.count().desc())
                            .limit(1)
                        ).first()
                        profile.mode = top[0] if top else None

                        values = conn.execute(
                            select(column).where(column.is_not(None)).limit(self.sample_size * 4)
                        ).scalars().all()
                        unique: List[str] = []
                        for value in values:
                            rendered = str(value)[:40]
                            if rendered not in unique:
                                unique.append(rendered)
                        profile.samples = unique[: self.sample_size]
                    except Exception:  # noqa: BLE001
                        pass

                profiles[name] = profile

        self.columns[table_name] = profiles

    # ---------------------------- 对外视图 ---------------------------- #

    def get_table_fields(self, table_name: str) -> pd.DataFrame:
        """字段画像表（与 notebook 的 get_table_fields 对齐）。"""
        profiles = self.columns[table_name]
        return pd.DataFrame(
            [
                {
                    "name": item.name,
                    "type": item.dtype,
                    "nullable": item.nullable,
                    "primary_key": item.primary_key,
                    "distinct": item.distinct,
                    "nan_count": item.nan_count,
                    "min": item.min_value,
                    "max": item.max_value,
                    "mode": item.mode,
                    "samples": " / ".join(item.samples),
                }
                for item in profiles.values()
            ]
        ).set_index("name", drop=False)

    def get_data_relations(self) -> pd.DataFrame:
        """外键关系表。"""
        return pd.DataFrame(self.foreign_keys)

    def get_table_sample(self, table_name: str, limit: int = 3) -> pd.DataFrame:
        """数据样例。"""
        with self.engine.connect() as conn:
            result = conn.execute(select(self._table(table_name)).limit(limit))
            return self._to_frame(result)

    def tables_catalog(self) -> str:
        """精简版表清单：完全由数据库元数据生成，不含任何人工语义标注。"""
        lines: List[str] = []
        for name in self.table_names:
            columns = list(self.columns.get(name, {}).keys())
            if not columns:
                columns = [col["name"] for col in self.inspector.get_columns(name)]
            lines.append(f"- {name}: {', '.join(columns)}")

        if self.foreign_keys:
            lines.append("")
            lines.append("外键关系：")
            for fk in self.foreign_keys:
                lines.append(
                    f"- {fk['constrained_table']}.{', '.join(fk['constrained_columns'])}"
                    f" -> {fk['referred_table']}.{', '.join(fk['referred_columns'])}"
                )
        return "\n".join(lines)

    def tables_schema(self, table_names: Sequence[str]) -> str:
        """详细版表结构（生成 / 改写 SQL 时用，含字段画像）。"""
        chunks: List[str] = []
        for name in table_names:
            if name not in self.table_names:
                continue
            buffer = [f"### 表 {name}", f"行数：{self.row_counts.get(name, '未知')}"]

            if self.primary_keys.get(name):
                buffer.append(f"主键：{', '.join(self.primary_keys[name])}")
            buffer.append("字段：")
            profiles = self.columns.get(name)
            if profiles:
                buffer.extend(profile.describe() for profile in profiles.values())
            else:
                buffer.extend(
                    f"  - {col['name']} {col['type']}"
                    for col in self.inspector.get_columns(name)
                )

            related = [
                fk
                for fk in self.foreign_keys
                if fk["constrained_table"] == name or fk["referred_table"] == name
            ]
            if related:
                buffer.append("关联：")
                for fk in related:
                    buffer.append(
                        f"  - {fk['constrained_table']}.{', '.join(fk['constrained_columns'])}"
                        f" -> {fk['referred_table']}.{', '.join(fk['referred_columns'])}"
                    )
            chunks.append("\n".join(buffer))
        return "\n\n".join(chunks)

    # ---------------------------- 校验 / 执行 ---------------------------- #

    def check_sql(self, sql: str) -> Tuple[bool, str]:
        """用 EXPLAIN 预编译 SQL：只做语法与标识符校验，不真正执行查询。"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text(f"EXPLAIN {sql}"))
            return True, "ok"
        except Exception as exc:  # noqa: BLE001 - 任何异常都视为校验失败
            return False, _format_db_error(exc)

    def execute_sql(self, sql: str, limit: Optional[int] = DEFAULT_LIMIT) -> pd.DataFrame:
        """执行 SQL；没有 LIMIT 时自动包裹一层限制返回行数。"""
        statement = sql.strip().rstrip(";").strip()
        if limit and not re.search(r"\blimit\b", statement, re.IGNORECASE):
            statement = f"SELECT * FROM (\n{statement}\n) AS _limited_rows LIMIT {int(limit)}"
        with self.engine.connect() as conn:
            return self._to_frame(conn.execute(text(statement)))


def _format_db_error(exc: Exception) -> str:
    """提取数据库返回的原始报错（去掉 SQLAlchemy 的外层包装与说明链接）。"""
    original = getattr(exc, "orig", None)
    detail = str(original) if original is not None else str(exc)
    detail = detail.split("\n")[0].strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


# --------------------------------------------------------------------------- #
# 通用小工具：SQL 清洗、结构解析、markdown 渲染
# --------------------------------------------------------------------------- #


def extract_sql(raw: str) -> str:
    """从 LLM 输出中抽取 SQL：去代码块包裹、去多余说明、去尾部分号。"""
    if not raw:
        return ""
    match = SQL_BLOCK.search(raw)
    sql = match.group(1) if match else raw
    sql = sql.strip()

    if not re.match(r"(?is)^\s*(select|with)\b", sql):
        located = re.search(r"(?is)\b(select|with)\b.+$", sql)
        if located:
            sql = located.group(0)

    sql = re.sub(r"(?i)^\s*sql\s*\n", "", sql.strip())
    return sql.strip().rstrip(";").strip()


def _strip_string_literals(sql: str) -> str:
    """把字符串字面量内容抹掉，避免关键字误判。"""
    out: List[str] = []
    quote: Optional[str] = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in ("'", '"', "`"):
            quote = char
            out.append(" ")
        else:
            out.append(char)
        index += 1
    return "".join(out)


def count_statements(sql: str) -> int:
    """统计语句条数（忽略字符串里的分号）。"""
    code = _strip_string_literals(sql)
    positions = [i for i, char in enumerate(code) if char == ";"]
    if not positions:
        return 1
    tail = code[positions[-1] + 1 :].strip()
    return len(positions) + (1 if tail else 0)


def _parse_table_list(raw: str, valid: Sequence[str], limit: int) -> List[str]:
    """解析「表选择」阶段 LLM 返回的表名列表。"""
    text = raw or ""
    names: List[str] = []

    block = re.search(r"\{.*\}", text, re.DOTALL)
    if block:
        try:
            payload = json.loads(block.group(0))
            if isinstance(payload, dict):
                candidate = payload.get("tables") or payload.get("table") or []
            else:
                candidate = payload
            if isinstance(candidate, str):
                candidate = [candidate]
            names = [str(item).strip() for item in candidate]
        except json.JSONDecodeError:
            names = []

    if not names:  # JSON 解析失败时，退化为在文本里找已知表名
        lowered = text.lower()
        names = [name for name in valid if re.search(rf"\b{re.escape(name.lower())}\b", lowered)]

    resolved: List[str] = []
    for name in names:
        key = name.strip(" `\"'[]").lower()
        matched = next((item for item in valid if item.lower() == key), None)
        if matched and matched not in resolved:
            resolved.append(matched)
    return resolved[:limit]


def _fmt_cell(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def df_to_markdown(frame: pd.DataFrame, max_rows: int = 20) -> str:
    """把 DataFrame 渲染成 markdown 表格（不依赖 tabulate）。"""
    if frame is None or frame.empty:
        return "(空结果)"
    head = frame.head(max_rows)
    columns = [str(column) for column in head.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for row in head.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(_fmt_cell(value) for value in row) + " |")
    if len(frame) > max_rows:
        lines.append("")
        lines.append(f"(共 {len(frame)} 行，以上为前 {max_rows} 行)")
    return "\n".join(lines)


def _shorten(text: str, limit: int = 800) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


# --------------------------------------------------------------------------- #
# LLM 适配层
# --------------------------------------------------------------------------- #


class LLMNotConfigured(RuntimeError):
    """没有可用的 LLM 配置。"""


class ChatModel:
    """LLM 统一接口：实现 chat(prompt) -> str 即可接入。"""

    name = "base"

    def chat(self, prompt: str) -> str:  # pragma: no cover - 抽象方法
        raise NotImplementedError


class OpenAICompatChat(ChatModel):
    """OpenAI 兼容接口（DashScope / DeepSeek / vLLM / Ollama 等）。"""

    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-flash",
        temperature: float = 0.1,
        timeout: int = 60,
        max_retry: int = 3,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retry = max_retry

    def chat(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retry + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code != 200:
                    raise RuntimeError(
                        f"接口返回 {response.status_code}: {response.text[:200]}"
                    )
                message = response.json()["choices"][0]["message"]
                content = (message.get("content") or "").strip()
                if not content:
                    # 推理模型在 token 预算被思考过程占满时 content 为空
                    content = (message.get("reasoning_content") or "").strip()
                if not content:
                    raise RuntimeError("模型返回空内容")
                return content
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.max_retry:
                    time.sleep(1.5 * attempt)
        raise RuntimeError(f"调用 OpenAI 兼容接口失败：{last_error}")


def build_chat_model(provider: Optional[str] = None, model: Optional[str] = None) -> ChatModel:
    """根据环境变量构造 LLM 客户端。"""
    provider = (provider or os.getenv("SQL_AGENT_LLM") or "deepseek").strip().lower()
    model = (model or os.getenv("SQL_AGENT_MODEL") or "").strip() or None

    deepseek_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if provider in ("deepseek", "openai") and deepseek_key:
        base_url = (
            os.getenv("SQL_AGENT_BASE_URL")
            or "https://api.deepseek.com"
        )
        return OpenAICompatChat(
            deepseek_key,
            base_url=base_url,
            model=model or "deepseek-flash",
        )

    raise LLMNotConfigured(
        "未检测到 DeepSeek API Key，请设置后重试：\n"
        "  PowerShell: $env:DEEPSEEK_API_KEY=\"你的 DeepSeek Key\"\n"
        "  bash: export DEEPSEEK_API_KEY=你的 DeepSeek Key\n"
        "也可以先运行 `python 作业一.py --selftest` 验证不含 LLM 的其余环节。"
    )


# --------------------------------------------------------------------------- #
# Prompt 模板
# --------------------------------------------------------------------------- #

PROMPT_TABLE_SELECT = """你是一位资深的数据分析工程师。数据库共 {table_count} 张表，下面的候选表清单给出了表名、字段列表与外键关系：

{catalog}

用户问题：{question}

请从候选表中选出回答问题所必需的表：
1. 只能从候选表中选择，最多 {max_tables} 张；只选真正需要的表，能少则少；
2. 如果问题是全库概览（例如介绍数据库、一共有多少张表），可以把候选表全部选上；
3. 需要多表关联时，按照外键关系把关联表一起选出；
4. 只输出 JSON，不要输出其他内容，格式如下：
{{"tables": ["table_a", "table_b"], "reason": "选择原因"}}
"""

PROMPT_SQL_GENERATE = """你是一位精通 {dialect} 的资深数据分析师。请依据给定的表结构，把用户问题翻译成一条可直接执行的 SQL。

【要求】
1. 只能使用下面给出的表和字段，字段名必须与表结构完全一致；
2. 只允许一条 SELECT 查询（可用 WITH / 子查询 / JOIN / 聚合），禁止 INSERT、UPDATE、DELETE、DDL 等写操作；
3. 多表查询按外键关系 JOIN，并正确使用表别名；
4. 明细类查询请加 LIMIT {limit}；统计类问题注意 GROUP BY 与 ORDER BY 的配合；
5. 结果列使用有业务含义的别名；
6. 排名 / TopN / 最高最低 / 最受欢迎这类问题，除了名称还必须输出排序所依据的指标（如数量、金额、次数），
   让结果本身能说明“为什么是它”；同一问题含多个子问题时，用并列子查询一次返回各自的排名结果；
7. 只输出 SQL，用 ```sql 代码块包裹，不要任何解释。

【表结构】
{schema}

【用户问题】
{question}
"""

PROMPT_SQL_REWRITE = """你是一位精通 {dialect} 的资深数据分析师。下面这条 SQL 在数据库上执行失败，请根据报错信息修正它。

【原始问题】
{question}

【执行失败的 SQL】
{sql}

【报错信息】
{error}

【可用表结构】
{schema}

【要求】
1. 只修正错误（字段名、表名、JOIN 条件、聚合与别名、语法等），保持查询意图不变；
2. 只允许一条 SELECT 查询，禁止写操作；
3. 只输出修正后的 SQL，用 ```sql 代码块包裹，不要任何解释。
"""

PROMPT_SUMMARY = """你是一位数据分析师。下面是用户问题、数据库概况、实际执行的 SQL 以及查询结果。

【用户问题】
{question}

【数据库概况】共 {table_count} 张表：{table_list}

【执行的 SQL】
{sql}

【查询结果】共 {rows} 行
{table}

请用中文给出简洁的结论性回答：
1. 先直接回答用户的问题（结论、数值、排名等）；
2. 再补充关键细节，数值保留合适的精度；
3. 不要复述 SQL，不要编造结果中不存在的数据，200 字以内；
4. 查询结果只覆盖部分表时，不要声称数据库只有这些表，涉及表数量以数据库概况为准。
"""


# --------------------------------------------------------------------------- #
# 2~7. SQL Agent
# --------------------------------------------------------------------------- #


class SQLAgentError(RuntimeError):
    """SQL 经过若干次改写仍然不可用。"""


@dataclass
class SQLAttempt:
    """一次失败的 SQL 尝试记录。"""

    sql: str
    error: str


@dataclass
class WorkflowResult:
    """一次完整问答的结果。"""

    question: str
    tables: List[str]
    sql: str
    attempts: List[SQLAttempt]
    data: pd.DataFrame
    answer: str
    elapsed: float

    def to_markdown(self) -> str:
        lines = [
            "=" * 72,
            f"问题：{self.question}",
            f"表选择：{', '.join(self.tables) if self.tables else '(无)'}",
            "",
            "SQL：",
            self.sql,
        ]
        if self.attempts:
            lines.append("")
            lines.append(f"校验失败并改写 {len(self.attempts)} 次：")
            for attempt in self.attempts:
                lines.append(f"  - 错误：{_shorten(attempt.error, 160)}")
        lines += [
            "",
            f"查询结果（{len(self.data)} 行）：",
            df_to_markdown(self.data, 20),
            "",
            f"回答：{self.answer}",
            f"耗时：{self.elapsed:.2f}s",
            "=" * 72,
        ]
        return "\n".join(lines)


class SQLAgent:
    """SQL Agent：表选择 -> 生成 -> 校验 -> 改写 -> 执行 -> 汇总。"""

    def __init__(
        self,
        parser: DatabaseParser,
        llm: ChatModel,
        *,
        max_rewrite: int = DEFAULT_MAX_REWRITE,
        limit: int = DEFAULT_LIMIT,
        max_tables: int = MAX_TABLES,
        verbose: bool = True,
    ) -> None:
        self.parser = parser
        self.llm = llm
        self.max_rewrite = max_rewrite
        self.limit = limit
        self.max_tables = max_tables
        self.verbose = verbose

    # ---------------------------- 日志 ---------------------------- #

    def _log(self, step: str, message: str) -> None:
        if self.verbose:
            print(f"[{step}] {message}", flush=True)

    # ---------------------- 2. 表选择 ---------------------- #

    def select_tables(self, question: str) -> List[str]:
        """让 LLM 从全库挑出回答问题所需的表。

        表清单只来自数据库元数据；LLM 不可用或输出无法解析时，
        退回全部表而不是人工预设的关键字映射，保证流程对任意库成立。
        """
        prompt = PROMPT_TABLE_SELECT.format(
            table_count=len(self.parser.table_names),
            catalog=self.parser.tables_catalog(),
            question=question,
            max_tables=self.max_tables,
        )
        try:
            raw = self.llm.chat(prompt)
        except Exception as exc:  # noqa: BLE001 - LLM 异常不应中断流程
            self._log("2 表选择", f"LLM 调用失败({exc})，退回全部表")
            return list(self.parser.table_names)

        tables = _parse_table_list(raw, self.parser.table_names, self.max_tables)
        if not tables:
            self._log("2 表选择", "解析失败，退回全部表")
            tables = list(self.parser.table_names)
        self._log("2 表选择", f"{tables}")
        return tables

    # ---------------------- 3. SQL 生成 ---------------------- #

    def generate_sql(self, question: str, tables: Sequence[str]) -> str:
        """基于选中表的详细结构生成 SQL。"""
        prompt = PROMPT_SQL_GENERATE.format(
            dialect=self.parser.db_type,
            schema=self.parser.tables_schema(tables),
            question=question,
            limit=self.limit,
        )
        sql = extract_sql(self.llm.chat(prompt))
        self._log("3 SQL 生成", f"{_shorten(sql, 200)}")
        return sql

    # ---------------------- 4. SQL 校验 ---------------------- #

    def validate_sql(self, sql: str, tables: Optional[Sequence[str]] = None) -> Tuple[bool, str]:
        """静态规则 + EXPLAIN 预编译校验，返回 (是否通过, 错误信息)。"""
        statement = (sql or "").strip()
        if not statement:
            return False, "SQL 为空"
        if not re.match(r"(?is)^(select|with)\b", statement):
            return False, "只允许 SELECT / WITH 查询"
        if count_statements(statement) > 1:
            return False, "只允许单条语句（检测到多条）"

        matched = FORBIDDEN_KEYWORDS.search(_strip_string_literals(statement))
        if matched:
            return False, f"包含被禁止的关键字：{matched.group(0).upper()}"

        passed, message = self.parser.check_sql(statement)
        if not passed:
            return False, message

        if tables:
            used = {
                name
                for name in self.parser.table_names
                if re.search(rf"\b{re.escape(name)}\b", statement, re.IGNORECASE)
            }
            extra = used - set(tables)
            if extra and self.verbose:
                self._log("4 SQL 校验", f"提示：SQL 引用了表选择阶段未选中的表 {sorted(extra)}")
        return True, "ok"

    # ---------------------- 5. SQL 改写 ---------------------- #

    def rewrite_sql(
        self,
        question: str,
        sql: str,
        error: str,
        tables: Sequence[str],
    ) -> str:
        """把报错信息交给 LLM，重写出一条可执行的 SQL。"""
        prompt = PROMPT_SQL_REWRITE.format(
            dialect=self.parser.db_type,
            question=question,
            sql=sql,
            error=_shorten(error, 600),
            schema=self.parser.tables_schema(tables),
        )
        rewritten = extract_sql(self.llm.chat(prompt))
        self._log("5 SQL 改写", f"{_shorten(rewritten, 200)}")
        return rewritten or sql

    # ---------------------- 6. SQL 执行 ---------------------- #

    def execute_sql(self, sql: str) -> pd.DataFrame:
        frame = self.parser.execute_sql(sql, limit=self.limit)
        self._log("6 SQL 执行", f"返回 {len(frame)} 行 / {len(frame.columns)} 列")
        return frame

    # ---------------------- 7. 结果汇总 ---------------------- #

    def summarize(self, question: str, sql: str, frame: pd.DataFrame) -> str:
        """把 SQL 执行结果汇总成自然语言结论。"""
        if frame is None or frame.empty:
            return "查询执行成功，但没有符合条件的数据。"
        names = self.parser.table_names
        table_list = ", ".join(names[:40])
        if len(names) > 40:
            table_list += f" 等 {len(names)} 张"
        prompt = PROMPT_SUMMARY.format(
            question=question,
            table_count=len(names),
            table_list=table_list,
            sql=sql,
            rows=len(frame),
            table=_shorten(df_to_markdown(frame, max_rows=30), 4000),
        )
        try:
            answer = self.llm.chat(prompt).strip()
        except Exception as exc:  # noqa: BLE001 - 汇总失败时退回结构化结果
            answer = f"（结果汇总失败：{exc}）查询返回 {len(frame)} 行，见下方表格。"
        self._log("7 结果汇总", _shorten(answer, 200))
        return answer

    # ---------------------- 全流程编排 ---------------------- #

    def run(self, question: str) -> WorkflowResult:
        """执行完整工作流。"""
        question = (question or "").strip()
        if not question:
            raise ValueError("问题不能为空")

        started = time.time()
        self._log("1 数据库解析", f"已解析 {len(self.parser.table_names)} 张表")

        tables = self.select_tables(question)
        sql = self.generate_sql(question, tables)

        attempts: List[SQLAttempt] = []
        frame: Optional[pd.DataFrame] = None

        for round_index in range(self.max_rewrite + 1):
            passed, message = self.validate_sql(sql, tables)
            if passed:
                try:
                    frame = self.execute_sql(sql)
                    break
                except Exception as exc:  # noqa: BLE001 - 执行期错误同样触发改写
                    passed, message = False, _format_db_error(exc)

            attempts.append(SQLAttempt(sql=sql, error=message))
            self._log("4 SQL 校验", f"未通过：{_shorten(message, 200)}")

            if round_index >= self.max_rewrite:
                raise SQLAgentError(
                    f"SQL 在 {self.max_rewrite} 次改写后仍不可用，最后一次错误：{message}"
                )
            sql = self.rewrite_sql(question, sql, message, tables)

        assert frame is not None
        answer = self.summarize(question, sql, frame)
        return WorkflowResult(
            question=question,
            tables=tables,
            sql=sql,
            attempts=attempts,
            data=frame,
            answer=answer,
            elapsed=time.time() - started,
        )


# --------------------------------------------------------------------------- #
# 自检 / CLI
# --------------------------------------------------------------------------- #


class _NoLLM(ChatModel):
    """占位模型：自检只覆盖不依赖 LLM 的确定性环节。"""

    name = "none"

    def chat(self, prompt: str) -> str:  # pragma: no cover - 自检不会调用
        raise RuntimeError("自检不调用 LLM")


def run_selftest(parser: DatabaseParser) -> int:
    """不依赖 LLM：用数据库自身元数据检验解析 / 校验 / 执行三个环节。

    所有检查项都从元数据派生，不含任何预置表名、预置 SQL 或预置答案。
    """
    print("\n[SELFTEST] 确定性环节自检（不调用 LLM）")
    if not parser.table_names:
        print("[SELFTEST] 数据库中没有可用表")
        return 1

    target = parser.table_names[0]
    quoted = parser.quote(target)
    count_sql = f"SELECT COUNT(*) AS n FROM {quoted}"
    frame = parser.execute_sql(count_sql, limit=5)
    agent = SQLAgent(parser, _NoLLM(), verbose=False)

    checks = {
        "解析出字段画像": bool(parser.columns.get(target)),
        "catalog 覆盖全部表": all(
            f"- {name}" in parser.tables_catalog() for name in parser.table_names
        ),
        "schema 文本非空": bool(parser.tables_schema(parser.table_names).strip()),
        "表选择结果可解析": _parse_table_list(
            json.dumps({"tables": parser.table_names[:2]}), parser.table_names, MAX_TABLES
        )
        == parser.table_names[:2],
        "合法 SQL 通过校验": agent.validate_sql(count_sql)[0],
        "拒绝写操作": not agent.validate_sql(f"DELETE FROM {quoted}")[0],
        "拒绝多语句": not agent.validate_sql(f"SELECT 1 FROM {quoted}; SELECT 2")[0],
        "拒绝未知字段": not agent.validate_sql(f"SELECT __no_such_column__ FROM {quoted}")[0],
        "执行结果与解析行数一致": int(frame.iloc[0, 0]) == parser.row_counts[target],
    }

    print("\n[SELFTEST] 检查项：")
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'} - {name}")
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        print(f"[SELFTEST] 失败 {len(failed)} 项")
        return 1
    print("[SELFTEST] 全部通过")
    return 0


def _resolve_db_url(db_target: str) -> str:
    """``--db`` 既可以是 SQLite 文件路径，也可以直接是任意 SQLAlchemy 连接串。"""
    if "://" in db_target:
        return db_target
    path = Path(db_target).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        raise FileNotFoundError(f"数据库文件不存在：{path}")
    return f"sqlite:///{path.as_posix()}"


def print_tables(parser: DatabaseParser) -> None:
    """列出库中的表与字段（纯本地元数据，不调用 LLM）。"""
    print(f"共 {len(parser.table_names)} 张表：")
    for name in parser.table_names:
        profiles = parser.columns.get(name) or {}
        columns = ", ".join(f"{profile.name} {profile.dtype}" for profile in profiles.values())
        print(f"\n- {name}（{parser.row_counts.get(name, 0)} 行）")
        if columns:
            print(f"    {columns}")


def describe_table(parser: DatabaseParser, table_name: str) -> int:
    """查看单张表的详细字段画像与样例（纯本地元数据，不调用 LLM）。"""
    if table_name not in parser.table_names:
        print(f"[错误] 没有表 {table_name}")
        print(f"可选：{', '.join(parser.table_names)}")
        similar = [name for name in parser.table_names if table_name.lower() in name.lower()]
        if similar:
            print(f"你可能想找：{', '.join(similar)}")
        return 2

    print(parser.tables_schema([table_name]))
    print("\n样例数据：")
    print(df_to_markdown(parser.get_table_sample(table_name, 5), 5))
    return 0


def _ask(agent: SQLAgent, question: str) -> bool:
    """跑一条问题，返回是否成功。"""
    try:
        result = agent.run(question)
    except SQLAgentError as exc:
        print(f"[错误] {exc}\n")
        return False
    except Exception as exc:  # noqa: BLE001 - 单条问题失败不影响后续
        print(f"[错误] {type(exc).__name__}: {exc}\n")
        return False
    print(result.to_markdown())
    print()
    return True


def _configure_stdout() -> None:
    """保留控制台原有编码（中文正常），仅把无法编码的字符替换掉，避免打印时崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):  # 某些环境不支持重配置
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_stdout()
    arg_parser = argparse.ArgumentParser(
        description="Week11 作业一：chinook.db 上的 SQL Agent 完整工作流"
    )
    arg_parser.add_argument(
        "question",
        nargs="*",
        help="自然语言问题（可不加引号，多个词会自动拼接）；不传则进入交互模式",
    )
    arg_parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 文件路径或 SQLAlchemy 连接串")
    arg_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="结果返回行数上限")
    arg_parser.add_argument("--max-rewrite", type=int, default=DEFAULT_MAX_REWRITE, help="SQL 最大改写次数")
    arg_parser.add_argument("--provider", choices=["deepseek"], default="deepseek", help="LLM 提供方")
    arg_parser.add_argument("--model", help="模型名")
    arg_parser.add_argument("--selftest", action="store_true", help="不调用 LLM，自检解析/校验/执行")
    arg_parser.add_argument("--tables", action="store_true", help="列出库中所有表与字段（不调用 LLM）")
    arg_parser.add_argument("--describe", metavar="TABLE", help="查看指定表的字段画像与样例（不调用 LLM）")
    arg_parser.add_argument("--quiet", action="store_true", help="关闭阶段日志")
    args = arg_parser.parse_args(argv)

    try:
        db_url = _resolve_db_url(args.db)
    except FileNotFoundError as exc:
        print(f"[错误] {exc}")
        return 2

    parser = DatabaseParser(db_url, verbose=not args.quiet)
    print()

    if args.tables:
        print_tables(parser)
        return 0
    if args.describe:
        return describe_table(parser, args.describe)

    if args.selftest:
        return run_selftest(parser)

    try:
        llm = build_chat_model(args.provider, args.model)
    except LLMNotConfigured as exc:
        print(f"[错误] {exc}")
        return 2
    print(f"[LLM] provider={llm.name} model={getattr(llm, 'model', '-')}\n")

    agent = SQLAgent(
        parser,
        llm,
        max_rewrite=args.max_rewrite,
        limit=args.limit,
        verbose=not args.quiet,
    )

    tokens = list(args.question)
    if tokens and tokens[0].lower() == "question":  # 兼容 `作业一.py question 你的问题`
        tokens = tokens[1:]
    question = " ".join(tokens).strip()
    if question:
        return 0 if _ask(agent, question) else 1

    if not sys.stdin.isatty():
        arg_parser.print_help()
        return 0

    print("请输入问题（直接回车退出）；不清楚有什么表可先运行 --tables")
    while True:
        try:
            question = input("问: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            break
        _ask(agent, question)
    return 0


if __name__ == "__main__":
    sys.exit(main())
