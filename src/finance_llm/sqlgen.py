"""Whitelist-only SQL builder and validator.

Security model: the analyst can only ever touch five tables and their
known columns. `build_sql` produces queries exclusively from a plan;
`validate_sql` is the gatekeeper for any SQL coming from an LLM —
anything that fails validation is discarded and the rule engine is used
instead.

Validation rejects: stacked statements, comment markers, DDL/DML/
administrative keywords, UNION/INTO injection, unknown identifiers,
unbalanced quotes/parens.
"""
from __future__ import annotations

import re

WHITELIST_TABLES = {"fact_gl", "fact_budget", "dim_date", "dim_account",
                    "dim_department"}

ALIASES = {"f": "fact_gl", "b": "fact_budget", "dt": "dim_date",
           "a": "dim_account", "d": "dim_department"}

WHITELIST_COLUMNS = {
    "fact_gl": {"month_id", "dept_id", "account_id", "actual"},
    "fact_budget": {"month_id", "dept_id", "account_id", "budget"},
    "dim_date": {"month_id", "month", "month_name", "month_num", "quarter", "year"},
    "dim_account": {"account_id", "account_name", "category", "owner_department"},
    "dim_department": {"dept_id", "department_name"},
}

BANNED_KEYWORDS = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|GRANT|REVOKE|ATTACH|DETACH|"
    r"LOAD|PRAGMA|VACUUM|COPY|UNION|INTO|EXPORT|IMPORT|RECURSIVE)\b",
    re.IGNORECASE)

ALLOWED_BARE_WORDS = {
    "SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "LIMIT", "AS", "ON",
    "JOIN", "AND", "OR", "NOT", "NULL", "IN", "BETWEEN", "IS", "CASE", "WHEN",
    "THEN", "ELSE", "END", "SUM", "AVG", "COUNT", "MIN", "MAX", "ABS", "ROUND",
    "CAST", "ASC", "DESC", "TRUE", "FALSE", "OVER", "PARTITION", "NULLIF",
}

BARE_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
IDENT_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)")


def _q(value: str) -> str:
    """Single-quote a literal with SQL escaping."""
    return "'" + value.replace("'", "''") + "'"


# ==================================================================== builder
def _time_condition(time: dict | None) -> str:
    if not time:
        return ""
    kind = time.get("type")
    if kind == "year":
        return f"dt.year = {int(time['value'])}"
    if kind == "month":
        return f"dt.year = {int(time['value'])} AND dt.month_num = {int(time['month'])}"
    if kind == "quarter":
        return f"dt.year = {int(time['value'])} AND dt.quarter = {int(time['quarter'])}"
    if kind == "last_month":
        return (f"dt.year = {int(time['value'])} AND "
                f"dt.month_num = {int(time['month'])}")
    if kind == "last_quarter":
        return (f"dt.year = {int(time['value'])} AND "
                f"dt.quarter = {int(time['quarter'])}")
    if kind == "range":
        return (f"dt.month >= {_q(str(time['start']))} AND "
                f"dt.month <= {_q(str(time['end']))}")
    return ""


def _category_for(metric: str) -> str | None:
    return {"revenue": "revenue", "cogs": "cogs", "opex": "opex"}.get(metric)


def _metric_expr(metric: str) -> str:
    if metric in ("revenue", "cogs", "opex"):
        return f"SUM(f.actual)"
    if metric == "gross_profit":
        return ("SUM(CASE WHEN a.category = 'revenue' THEN f.actual "
                "WHEN a.category = 'cogs' THEN -f.actual END)")
    if metric == "operating_profit":
        return ("SUM(CASE WHEN a.category = 'revenue' THEN f.actual "
                "WHEN a.category = 'cogs' THEN -f.actual "
                "WHEN a.category = 'opex' THEN -f.actual END)")
    if metric == "variance":
        return "SUM(f.actual) - SUM(b.budget)"
    if metric == "attainment":
        return "(SUM(f.actual) / NULLIF(SUM(b.budget), 0)) * 100.0"
    raise ValueError(f"cannot build SQL for metric {metric!r}")


_DIM_COLUMN = {"department": "d.department_name", "account": "a.account_name",
               "category": "a.category", "month": "dt.month",
               "quarter": "dt.quarter", "year": "dt.year"}


def build_sql(plan: dict, with_budget: bool | None = None) -> str:
    """Render a plan (from the rule engine) into whitelist-checked SQL."""
    metric = plan["metric"]
    if metric == "unknown":
        raise ValueError("cannot build SQL for unknown metric")

    needs_budget = metric in ("variance", "attainment")
    if with_budget is None:
        with_budget = needs_budget

    select_expr = _metric_expr(metric)

    joins = ["fact_gl f"]
    if with_budget:
        joins.append("fact_budget b ON f.month_id = b.month_id AND "
                     "f.dept_id = b.dept_id AND f.account_id = b.account_id")
    joins += ["dim_account a ON f.account_id = a.account_id",
              "dim_department d ON f.dept_id = d.dept_id",
              "dim_date dt ON f.month_id = dt.month_id"]

    where = []
    category = _category_for(metric)
    if category:
        where.append(f"a.category = {_q(category)}")
    time_sql = _time_condition(plan.get("time"))
    if time_sql:
        where.append(time_sql)
    for flt in plan.get("filters", []):
        where.append(f"{_DIM_COLUMN[flt['field']]} = {_q(flt['value'])}")

    group_cols = [plan["dims"]] if isinstance(plan.get("dims"), str) else plan.get("dims", [])
    group_sql = ""
    select_extra = ""
    if group_cols:
        cols = [f"{_DIM_COLUMN[c]} AS {c}" for c in group_cols]
        select_extra = ", " + ", ".join(cols)
        group_sql = " GROUP BY " + ", ".join(_DIM_COLUMN[c] for c in group_cols)

    order_sql = ""
    top_n = plan.get("top_n")
    if top_n:
        order_sql = f" ORDER BY {select_expr} DESC LIMIT {int(top_n)}"
    elif group_cols and plan.get("sort"):
        order_sql = f" ORDER BY {select_expr} DESC"

    sql = (f"SELECT {select_expr} AS {metric}{select_extra} "
           f"FROM {' JOIN '.join(joins)}")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += group_sql + order_sql
    return sql


# ================================================================== validator
def validate_sql(sql: str) -> bool:
    """Strict gatekeeper: True only for SELECTs over whitelist objects."""
    if not sql or not isinstance(sql, str):
        return False
    stripped = sql.strip()
    if not stripped.upper().startswith("SELECT"):
        return False
    if "FROM" not in stripped.upper():
        return False
    if len(re.findall(r"\bSELECT\b", stripped, re.IGNORECASE)) > 1:
        return False  # no subqueries / stacked selects
    if ";" in stripped or "--" in stripped or "/*" in stripped or "*/" in stripped:
        return False
    if BANNED_KEYWORDS.search(stripped):
        return False
    if stripped.count("'") % 2 != 0 or stripped.count("(") != stripped.count(")"):
        return False

    # words introduced as aliases (AS x) are user-facing names, not columns
    alias_words = {m.group(1) for m in
                   re.finditer(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)", stripped, re.IGNORECASE)}

    # qualifier.column pairs must be whitelisted
    for qualifier, column in IDENT_RE.findall(stripped):
        table = ALIASES.get(qualifier)
        if table is None or column not in WHITELIST_COLUMNS[table]:
            return False

    # any bare table mention must be whitelisted
    for table in WHITELIST_TABLES:
        if re.search(rf"\b{table}\b", stripped) and table not in ("fact_gl", "fact_budget"):
            pass  # dim tables may appear; they are whitelisted anyway

    # remaining bare words must be allowed keywords or part of the whitelist
    for word in BARE_WORD_RE.findall(stripped):
        upper = word.upper()
        if upper in ALLOWED_BARE_WORDS:
            continue
        if word in alias_words:
            continue
        if word in WHITELIST_TABLES:
            continue
        if any(word in cols for cols in WHITELIST_COLUMNS.values()):
            continue
        if word in ALIASES:
            continue
        return False
    return True
