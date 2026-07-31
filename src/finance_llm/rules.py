"""Rule engine: natural language -> structured query plan.

Pure keyword/pattern parsing — deterministic, offline, no LLM required.
Handles metrics, time ranges, dimensions, filters, comparisons and
top-N. Ambiguities resolve with explicit phrase checks first (e.g.
"marketing spend" -> account marketing_spend, "in marketing" ->
department sales/marketing/rnd/operations).
"""
from __future__ import annotations

import re

from finance_llm.generate import ACCOUNTS, DEPARTMENTS

MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
          "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
          "november": 11, "december": 12}
MONTH_SHORT = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
               "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
QUARTERS = {"q1": 1, "q2": 2, "q3": 3, "q4": 4,
            "first quarter": 1, "second quarter": 2,
            "third quarter": 3, "fourth quarter": 4}
YEARS = [2023, 2024, 2025]

_ACCOUNT_ALIASES = {
    "marketing spend": "marketing_spend",
    "marketing expense": "marketing_spend",
    "cost of goods": "cost_of_goods",
    "cogs": "cost_of_goods",
    "cloud": "cloud_infrastructure",
    "salaries": "salaries",
    "rent": "rent",
    "depreciation": "depreciation",
}


def _has(text: str, *words: str) -> bool:
    return any(f" {w} " in f" {text} " or text.startswith(w + " ") or
               text.endswith(" " + w) for w in words)


def _year_in(text: str) -> int | None:
    for y in YEARS:
        if str(y) in text:
            return y
    return None


def _month_in(text: str) -> int | None:
    for name, num in MONTHS.items():
        if name in text:
            return num
    for name, num in MONTH_SHORT.items():
        if re.search(rf"\b{name}\b", text):
            return num
    return None


def parse_question(question: str) -> dict:
    """Turn a natural-language finance question into a query plan."""
    text = question.lower()
    plan = {"metric": "unknown", "dims": [], "time": None, "compare": None,
            "filters": [], "top_n": None, "question": question}

    # ------------------------------------------------------------- metric
    if _has(text, "attainment", "budget attainment"):
        plan["metric"] = "attainment"
    elif _has(text, "variance"):
        plan["metric"] = "variance"
    elif _has(text, "revenue", "sales", "topline") or "top line" in text:
        plan["metric"] = "revenue"
    elif "gross profit" in text or "gross margin" in text or _has(text, "gross"):
        plan["metric"] = "gross_profit"
    elif _has(text, "operating profit", "ebitda", "net profit", "profit"):
        plan["metric"] = "operating_profit"
    elif "cost of goods" in text or _has(text, "cogs"):
        plan["metric"] = "cogs"
    elif _has(text, "opex", "operating expense", "expense", "expenses",
              "spend", "cost", "costs", "salary", "salaries"):
        plan["metric"] = "opex"

    # ----------------------------------------------------------- compare
    if "vs budget" in text or "versus budget" in text or "against budget" in text:
        plan["compare"] = {"type": "vs_budget"}
    if ("year over year" in text or "yoy" in text or "vs last year" in text
            or "compared to last year" in text or _has(text, "growth")):
        plan["compare"] = {"type": "growth"}
    if "vs last month" in text or "vs previous month" in text or "mom" in text:
        plan["compare"] = {"type": "growth", "granularity": "month"}

    # -------------------------------------------------------------- time
    if _has(text, "last month", "previous month"):
        plan["time"] = {"type": "last_month"}
    elif _has(text, "last quarter", "previous quarter"):
        plan["time"] = {"type": "last_quarter"}
    elif "ytd" in text or "year to date" in text:
        plan["time"] = {"type": "ytd", "value": _year_in(text)}
    else:
        year = _year_in(text)
        month = _month_in(text)
        quarter = None
        for name, num in QUARTERS.items():
            if name in text:
                quarter = num
                break
        if quarter is not None and year is not None:
            plan["time"] = {"type": "quarter", "value": year, "quarter": quarter}
        elif month is not None and year is not None:
            plan["time"] = {"type": "month", "value": year, "month": month}
        elif year is not None:
            plan["time"] = {"type": "year", "value": year}

    # ------------------------------------------------------------ filters
    # explicit account phrases first (disambiguates dept names)
    for alias, account in _ACCOUNT_ALIASES.items():
        if alias in text:
            plan["filters"].append({"field": "account", "value": account})
            break
    for name, account in ((a[0].replace("_", " "), a[0]) for a in ACCOUNTS):
        if name in text:
            plan["filters"].append({"field": "account", "value": account})
            break
    if not any(f["field"] == "account" for f in plan["filters"]):
        for dept in DEPARTMENTS:
            if dept in text:
                plan["filters"].append({"field": "department", "value": dept})
                break

    # -------------------------------------------------------------- dims
    if _has(text, "by department", "per department", "across departments",
            "each department"):
        plan["dims"] = ["department"]
    elif _has(text, "by account", "per account", "by line item"):
        plan["dims"] = ["account"]
    elif _has(text, "by category"):
        plan["dims"] = ["category"]
    elif _has(text, "by month", "monthly", "per month", "by quarter", "quarterly"):
        plan["dims"] = ["month"] if "month" in text else ["quarter"]

    # ------------------------------------------------------------- top N
    m = re.search(r"top\s+(\d+)", text)
    if m:
        plan["top_n"] = int(m.group(1))
        if plan["dims"] == [] and "account" in text:
            plan["dims"] = ["account"]

    # growth defaults to year-over-year unless a month-level cue exists
    if plan["compare"] and plan["compare"].get("type") == "growth":
        plan["compare"].setdefault("granularity", "month" if "month" in text else "year")

    return plan
