"""Plan execution and answer formatting.

Pipeline: plan -> concrete time resolution -> whitelist SQL -> DuckDB ->
formatted human answer + markdown table. Growth questions run two
queries (current vs previous period) and report the % change.
"""
from __future__ import annotations

import pandas as pd

from finance_llm.rules import parse_question
from finance_llm.sqlgen import build_sql, validate_sql

GUIDANCE = (
    "I can answer finance questions like:\n"
    "- revenue / expenses / gross profit / EBITDA for a month, quarter or year\n"
    "- by department or by account, monthly or quarterly trends\n"
    "- actual vs budget variance and budget attainment\n"
    "- year-over-year or month-over-month growth\n"
    "- top N revenue accounts\n"
    "Try e.g.: \"total revenue in 2025\", \"opex by department for Q3 2024\", "
    "\"revenue vs budget last month\".")


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def _md_table(df: pd.DataFrame) -> str:
    """Dependency-free markdown table (no tabulate required)."""
    if df is None or len(df) == 0:
        return ""
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.iterrows():
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append(f"{v:,.0f}" if abs(v) >= 100 else f"{v:.2f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _resolve_time(warehouse, time: dict | None) -> dict | None:
    """Resolve relative periods (last month, YTD) against the data."""
    if not time:
        return None
    last = warehouse.query("SELECT MAX(month) AS m, MAX(year) AS y, "
                           "MAX(month_num) AS mn FROM dim_date").iloc[0]
    if time["type"] == "last_month":
        y, m = int(last["y"]), int(last["mn"])
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
        return {"type": "month", "value": y, "month": m}
    if time["type"] == "last_quarter":
        y, m = int(last["y"]), int(last["mn"])
        q = (m - 1) // 3 + 1
        if q == 1:
            y, q = y - 1, 4
        else:
            q -= 1
        return {"type": "quarter", "value": y, "quarter": q}
    if time["type"] == "ytd":
        y = time.get("value") or int(last["y"])
        return {"type": "year", "value": y}
    return dict(time)


def _previous_period(time: dict | None) -> dict | None:
    """Shift a resolved time one period back (for growth questions)."""
    if not time:
        return None
    if time["type"] == "year":
        return {"type": "year", "value": time["value"] - 1}
    if time["type"] == "quarter":
        if time["quarter"] == 1:
            return {"type": "quarter", "value": time["value"] - 1, "quarter": 4}
        return {"type": "quarter", "value": time["value"], "quarter": time["quarter"] - 1}
    if time["type"] == "month":
        if time["month"] == 1:
            return {"type": "month", "value": time["value"] - 1, "month": 12}
        return {"type": "month", "value": time["value"], "month": time["month"] - 1}
    return time


def execute_plan(warehouse, plan: dict) -> dict:
    """Run a plan; returns {"frames": [...], "sql": str}."""
    if plan["metric"] == "unknown":
        return {"frames": [], "sql": None}
    resolved = _resolve_time(warehouse, plan.get("time"))
    current = dict(plan)
    current["time"] = resolved
    # "X vs budget" questions become variance queries against fact_budget
    if ((current.get("compare") or {}).get("type") == "vs_budget"
            and current["metric"] not in ("variance", "attainment")):
        current["metric"] = "variance"
    sql = build_sql(current)
    frames = [warehouse.query(sql)]
    if (plan.get("compare") or {}).get("type") == "growth":
        if resolved is None:  # no explicit period -> compare latest year
            last_year = int(warehouse.query(
                "SELECT MAX(year) AS y FROM dim_date")["y"][0])
            resolved = {"type": "year", "value": last_year}
        previous = dict(plan)
        previous["time"] = _previous_period(resolved)
        frames.append(warehouse.query(build_sql(previous)))
    return {"frames": frames, "sql": sql}


def format_answer(plan: dict, frames: list[pd.DataFrame],
                  executed_sql: str | None = None) -> dict:
    """Compose a human answer + markdown table from executed frames."""
    metric = plan["metric"]
    labels = {"revenue": "Revenue", "cogs": "COGS", "opex": "Operating expenses",
              "gross_profit": "Gross profit",
              "operating_profit": "Operating profit",
              "variance": "Actual vs budget variance",
              "attainment": "Budget attainment"}
    label = labels.get(metric, metric.replace("_", " ").title())

    if not frames:
        return {"answer": GUIDANCE, "table": None, "sql": None, "metric": "unknown"}

    df = frames[0]
    value_col = df.columns[0]
    v = float(df.iloc[0][value_col])
    compare = plan.get("compare") or {}
    sqls = [executed_sql] if executed_sql else []
    lines = []

    if compare.get("type") == "growth" and len(frames) == 2:
        current_v = v
        prev_v = float(frames[1].iloc[0][frames[1].columns[0]])
        if prev_v != 0:
            change = (current_v - prev_v) / abs(prev_v) * 100
            lines.append(f"{label}: {_money(current_v)} "
                         f"({_pct(change)} vs previous period)")
        else:
            lines.append(f"{label}: {_money(current_v)} (no prior-period data)")
    elif metric == "attainment":
        lines.append(f"{label}: {v:.1f}%")
    elif metric == "variance" or compare.get("type") == "vs_budget":
        sign = "above" if v >= 0 else "below"
        lines.append(f"Actual vs budget variance: {_money(abs(v))} {sign} budget")
    else:
        lines.append(f"{label}: {_money(v)}")

    table = None
    if len(df.columns) > 1:
        table = _md_table(df)

    return {"answer": "\n".join(lines), "table": table,
            "sql": sqls[0], "metric": metric}


def ask(warehouse, question: str, llm=None, use_llm: bool = False) -> dict:
    """Orchestrator: LLM first (validated), rule engine as fallback."""
    if use_llm and llm is not None and llm.available:
        schema = warehouse.schema_metadata()
        schema_text = (f"Tables: {', '.join(schema['tables'])}\n"
                       f"Departments: {', '.join(schema['departments'])}\n"
                       f"Categories: {', '.join(schema['account_categories'])}\n"
                       f"Data range: {schema['first_month']} to {schema['last_month']}")
        sql = llm.translate(question, schema_text)
        if sql and validate_sql(sql):
            try:
                df = warehouse.query(sql)
                plan = {"metric": "revenue", "dims": [], "time": None,
                        "compare": None, "filters": [], "top_n": None,
                        "question": question}
                cols = df.columns.tolist()
                metric = cols[0] if cols else "value"
                markdown = _md_table(df)
                result = {"answer": f"Result: {markdown}"
                          if len(cols) > 1 else
                          f"Result: {float(df.iloc[0, 0]):,.2f}",
                          "table": markdown,
                          "sql": sql, "metric": metric, "source": "llm"}
                return result
            except Exception:
                pass  # execution failed -> fall through to rules

    plan = parse_question(question)
    executed = execute_plan(warehouse, plan)
    frames = executed["frames"]
    result = format_answer(plan, frames, executed_sql=executed["sql"])
    result["source"] = "rules"
    return result
