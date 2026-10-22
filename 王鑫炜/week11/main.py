"""命令行入口：默认真实模型；--demo 显式启用固定案例回放。"""

import argparse
import json
import sys
from pathlib import Path

from database import Database
from llm import ChatModel, ModelError, ReplayModel, load_settings
from sql_agent import SQLAgent


ROOT = Path(__file__).resolve().parent


def load_cases():
    return json.loads((ROOT / "examples" / "cases.json").read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Chinook SQL Agent：七步只读问答工作流")
    parser.add_argument("question", nargs="?", help="自然语言问题；在线模式必须提供")
    parser.add_argument("--demo", metavar="ID", help="离线案例编号，all 表示全部案例")
    parser.add_argument("--list-demos", action="store_true", help="列出固定演示问题")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "chinook.db")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--max-rows", type=int, default=50)
    parser.add_argument("--max-rewrites", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=2.0, help="每次 SQL 编译/执行的秒数预算")
    parser.add_argument("--output", type=Path, help="将结构化结果写入指定 JSON 文件")
    args = parser.parse_args(argv)
    cases = load_cases()
    if args.list_demos:
        for case in cases:
            print("{}: {}".format(case["id"], case["question"]))
        return 0
    if args.demo and args.question:
        parser.error("--demo 使用预设问题，不能同时传入自定义问题")
    if not args.demo and not args.question:
        parser.error("请提供问题，或使用 --demo all")
    try:
        db = Database(args.db, max_rows=args.max_rows, timeout_seconds=args.timeout)
        if args.demo:
            selected = cases if args.demo == "all" else [c for c in cases if c["id"] == args.demo]
            if not selected:
                raise ValueError("未知演示编号；用 --list-demos 查看")
            results = []
            for case in selected:
                item = SQLAgent(db, ReplayModel(case), args.max_rewrites).run(case["question"])
                item["demo_id"] = case["id"]
                results.append(item)
            output = results if args.demo == "all" else results[0]
        else:
            model = ChatModel(load_settings(args.env_file))
            output = SQLAgent(db, model, args.max_rewrites).run(args.question)
            results = [output]
        text = json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)
        print(text)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        return 0 if all(r["status"] in ("ok", "needs_clarification") for r in results) else 1
    except (ValueError, ModelError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
