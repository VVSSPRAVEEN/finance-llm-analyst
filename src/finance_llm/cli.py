"""Command-line interface for the Finance LLM Analyst.

Usage (from repo root, after `pip install -r requirements.txt`):
    python -m finance_llm.cli init
    python -m finance_llm.cli ask "total revenue in 2025"
    python -m finance_llm.cli ask "opex by department in Q3 2024" --llm
    python -m finance_llm.cli repl
    python -m finance_llm.cli eval
    python -m finance_llm.cli tune [--live]
    python -m finance_llm.cli all
"""
from __future__ import annotations

import argparse
import pathlib
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from finance_llm.answers import ask  # noqa: E402
from finance_llm.llm import LLMClient  # noqa: E402
from finance_llm.tuning import GOLDEN, run_tuning  # noqa: E402
from finance_llm.warehouse import Warehouse  # noqa: E402


def cmd_init(args) -> int:
    Warehouse(args.db).build(force=args.force)
    print(f"Warehouse ready: {args.db}")
    return 0


def cmd_ask(args) -> int:
    wh = Warehouse(args.db)
    llm = LLMClient() if args.llm else None
    result = ask(wh, args.question, llm=llm, use_llm=bool(args.llm))
    print(result["answer"])
    if result.get("table"):
        print()
        print(result["table"])
    if args.show_sql and result.get("sql"):
        print()
        print("SQL:", result["sql"])
    print(f"(source: {result.get('source', 'rules')})")
    wh.close()
    return 0


def cmd_repl(args) -> int:
    wh = Warehouse(args.db)
    llm = LLMClient() if args.llm else None
    print("Finance analyst REPL — type a question, 'exit' to quit.")
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in ("exit", "quit"):
            break
        if not question:
            continue
        result = ask(wh, question, llm=llm, use_llm=bool(args.llm))
        print(result["answer"])
        if result.get("table"):
            print(result["table"])
    wh.close()
    return 0


def cmd_eval(args) -> int:
    from finance_llm.answers import execute_plan, format_answer
    from finance_llm.rules import parse_question

    wh = Warehouse(args.db)
    passed = failed = 0
    for g in GOLDEN:
        plan = parse_question(g["q"])
        if plan["metric"] == "unknown":
            failed += 1
            print(f"FAIL (unparsed): {g['q']}")
            continue
        executed = execute_plan(wh, plan)
        frames = executed["frames"]
        if not frames:
            failed += 1
            print(f"FAIL (no result): {g['q']}")
            continue
        result = format_answer(plan, frames, executed_sql=executed["sql"])
        if result["metric"] == g["metric"]:
            passed += 1
            print(f"PASS: {g['q']} -> {result['answer']}")
        else:
            failed += 1
            print(f"FAIL (metric {result['metric']} != {g['metric']}): {g['q']}")
    print(f"\nGolden set: {passed} passed, {failed} failed")
    wh.close()
    return 0 if failed == 0 else 1


def cmd_tune(args) -> int:
    out = run_tuning(out_dir=args.out, llm=LLMClient(), live=args.live)
    print(f"Winner: {out['winner']['name']} (score {out['winner']['score']})")
    for r in out["results"]:
        print(f"  {r['name']:16s} score={r['score']}")
    print(f"Report: {out['report']}")
    return 0


def cmd_all(args) -> int:
    from argparse import Namespace
    cmd_init(Namespace(db=args.db, force=args.force))
    for question in ("total revenue in 2025",
                     "opex by department in Q3 2024",
                     "revenue vs budget last month"):
        args.question = question
        args.show_sql = False
        args.llm = False
        cmd_ask(args)
    cmd_eval(args)
    cmd_tune(Namespace(out="docs", live=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finance LLM Analyst")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Build the DuckDB warehouse")
    p.add_argument("--db", default="finance.db")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("ask", help="Ask a finance question")
    p.add_argument("question")
    p.add_argument("--db", default="finance.db")
    p.add_argument("--llm", action="store_true", help="Try the LLM first")
    p.add_argument("--show-sql", action="store_true")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("repl", help="Interactive Q&A session")
    p.add_argument("--db", default="finance.db")
    p.add_argument("--llm", action="store_true")
    p.set_defaults(func=cmd_repl)

    p = sub.add_parser("eval", help="Run the golden question set")
    p.add_argument("--db", default="finance.db")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("tune", help="Prompt-tuning harness")
    p.add_argument("--out", default="docs")
    p.add_argument("--live", action="store_true",
                   help="Score variants with the real LLM (uses API)")
    p.set_defaults(func=cmd_tune)

    p = sub.add_parser("all", help="init + 3 asks + eval + tune")
    p.add_argument("--db", default="finance.db")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_all)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
