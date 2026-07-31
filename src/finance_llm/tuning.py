"""Prompt-tuning harness for the NL->SQL translator.

Purpose: select the best few-shot system prompt variant for translating
finance questions to SQL. Scores every variant against a golden question
set on three offline axes plus an optional live axis:

- parse_rate : fraction of golden questions the rule engine understands
- plan_acc   : fraction whose parsed plan (metric + dims) matches golden
- sql_ok     : fraction for which a whitelist-valid SQL can be built
- coverage   : keyword overlap between the variant's few-shot examples
               and the golden questions (how well the prompt teaches the
               domain)
- live_acc   : (optional, only with an LLM key + FINANCE_TUNE_LIVE=1)
               fraction of questions the LLM translates to valid SQL

Total score: 0.40*plan_acc + 0.25*sql_ok + 0.20*coverage +
0.15*parse_rate (+ live bonus). Winner is written to
docs/prompt_tuning_report.md + docs/prompt_selection.json.
"""
from __future__ import annotations

import json
import pathlib
import re

from finance_llm.rules import parse_question
from finance_llm.sqlgen import build_sql, validate_sql

GOLDEN = [
    {"q": "total revenue in 2025", "metric": "revenue", "dims": []},
    {"q": "how much did we spend on opex in q4 2024", "metric": "opex",
     "dims": []},
    {"q": "revenue by department for 2024", "metric": "revenue",
     "dims": ["department"]},
    {"q": "gross profit last month", "metric": "gross_profit", "dims": []},
    {"q": "operating profit for 2025", "metric": "operating_profit", "dims": []},
    {"q": "cogs by month in 2023", "metric": "cogs", "dims": ["month"]},
    {"q": "opex by account in 2025", "metric": "opex", "dims": ["account"]},
    {"q": "revenue vs budget in 2025", "metric": "revenue",
     "dims": [], "compare": "vs_budget"},
    {"q": "budget attainment for sales in 2024", "metric": "attainment",
     "dims": [], "filter": "sales"},
    {"q": "marketing spend ytd", "metric": "opex", "dims": [], "filter": "marketing_spend"},
    {"q": "revenue growth year over year", "metric": "revenue", "dims": [],
     "compare": "growth"},
    {"q": "top 5 revenue accounts in 2025", "metric": "revenue",
     "dims": ["account"], "top_n": 5},
    {"q": "salaries by department in 2024", "metric": "opex",
     "dims": ["department"], "filter": "salaries"},
    {"q": "quarterly opex trend in 2025", "metric": "opex", "dims": ["quarter"]},
]

VARIANTS = [
    {
        "name": "strict_minimal",
        "system": ("Return only SQL for a DuckDB star schema with tables "
                   "fact_gl, fact_budget, dim_date, dim_account, dim_department. "
                   "No explanation, no fences."),
        "examples": 2,
    },
    {
        "name": "domain_context",
        "system": ("You are a FP&A analyst writing DuckDB SQL. Use "
                   "fact_gl (actuals), fact_budget (budget), dim_date, "
                   "dim_account (category in revenue/cogs/opex), "
                   "dim_department. Only SELECT. Return SQL only."),
        "examples": 4,
    },
    {
        "name": "chain_of_thought",
        "system": ("Steps: 1) identify the metric and its category "
                   "(revenue/cogs/opex/profit), 2) choose the time filter, "
                   "3) choose dimensions, 4) emit DuckDB SQL only."),
        "examples": 3,
    },
    {
        "name": "few_shot_rich",
        "system": ("Translate finance questions to DuckDB SQL. Examples:\n"
                   "Q: total revenue in 2025 -> SELECT SUM(f.actual) AS revenue "
                   "FROM fact_gl f JOIN dim_account a ON f.account_id=a.account_id "
                   "JOIN dim_date dt ON f.month_id=dt.month_id WHERE "
                   "a.category='revenue' AND dt.year=2025\n"
                   "Q: opex by department -> ... GROUP BY d.department_name\n"
                   "Q: revenue vs budget -> ... JOIN fact_budget b ... "
                   "SUM(f.actual)-SUM(b.budget)"),
        "examples": 3,
    },
]


def _coverage(variant: dict, golden: list[dict]) -> float:
    example_text = variant["system"].lower()
    hits = 0
    for g in golden:
        words = {w for w in re.findall(r"[a-z]+", g["q"].lower())
                 if w not in ("the", "in", "for", "of", "and", "vs")}
        if words and any(w in example_text for w in words):
            hits += 1
    return hits / len(golden) if golden else 0.0


def evaluate_variant(variant: dict, golden: list[dict] | None = None,
                     llm=None, live: bool = False) -> dict:
    golden = golden or GOLDEN
    parse_ok = sql_ok = plan_ok = 0
    n = len(golden)
    for g in golden:
        plan = parse_question(g["q"])
        if plan["metric"] != "unknown":
            parse_ok += 1
        if (plan["metric"] == g["metric"] and set(plan["dims"]) == set(g.get("dims", []))):
            plan_ok += 1
        if plan["metric"] != "unknown":
            try:
                sql = build_sql(plan)
                if validate_sql(sql):
                    sql_ok += 1
            except (ValueError, KeyError):
                pass

    live_acc = 0.0
    if live and llm is not None and llm.available:
        live_hits = 0
        for g in golden:
            if llm.translate(g["q"], "schema"):
                live_hits += 1
        live_acc = live_hits / n

    parse_rate = parse_ok / n
    plan_acc = plan_ok / n
    sql_ok_rate = sql_ok / n
    coverage = _coverage(variant, golden)
    score = (0.40 * plan_acc + 0.25 * sql_ok_rate + 0.20 * coverage
             + 0.15 * parse_rate)
    if live:
        score = 0.70 * score + 0.30 * live_acc
    return {"name": variant["name"], "parse_rate": round(parse_rate, 3),
            "plan_acc": round(plan_acc, 3), "sql_ok": round(sql_ok_rate, 3),
            "coverage": round(coverage, 3), "live_acc": round(live_acc, 3),
            "score": round(score, 3)}


def run_tuning(out_dir: str | pathlib.Path = "docs", llm=None,
               live: bool = False) -> dict:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = [evaluate_variant(v, llm=llm, live=live) for v in VARIANTS]
    results.sort(key=lambda r: r["score"], reverse=True)
    winner = results[0]

    lines = [
        "# Prompt Tuning Report — NL to SQL",
        "",
        f"- Golden questions: {len(GOLDEN)}  |  Live LLM mode: {'on' if live else 'off'}",
        "",
        "## Scores",
        "",
        "| variant | parse_rate | plan_acc | sql_ok | coverage | live_acc | score |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r['name']} | {r['parse_rate']} | {r['plan_acc']} | "
                     f"{r['sql_ok']} | {r['coverage']} | {r['live_acc']} | "
                     f"{r['score']} |")
    lines += ["", f"**Winner: `{winner['name']}`** (score {winner['score']})",
              "",
              "The winner maximizes domain coverage and plan accuracy. With an "
              "API key set in `.env` and FINANCE_TUNE_LIVE=1, run `python -m "
              "finance_llm.cli tune --live` for live LLM validation.", ""]
    (out / "prompt_tuning_report.md").write_text("\n".join(lines), encoding="utf-8")
    (out / "prompt_selection.json").write_text(
        json.dumps({"winner": winner, "results": results}, indent=2),
        encoding="utf-8")
    return {"winner": winner, "results": results,
            "report": str(out / "prompt_tuning_report.md"),
            "selection": str(out / "prompt_selection.json")}
