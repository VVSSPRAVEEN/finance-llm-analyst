"""Deterministic synthetic financial warehouse data.

Star schema:
- dim_date       : 36 months (2023-01 .. 2025-12)
- dim_department : sales, marketing, rnd, operations
- dim_account    : 22 accounts (6 revenue, 3 cogs, 13 opex); each account
                   is owned by exactly one department
- fact_gl        : actuals, grain = (month x account) = 792 rows; each
                   account is owned by exactly one department
- fact_budget    : budget at the same grain

Revenue accounts grow ~1.2%/month with year-end seasonality; opex is
mostly flat with slow drift. Budget = actual * (1 + N(0, 0.04)) so
attainment sits in a realistic 90-110% band. Seeded (42): fully
reproducible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 42
N_MONTHS = 36
START = "2023-01"

DEPARTMENTS = ["sales", "marketing", "rnd", "operations"]

# (account_name, category, owner_department, monthly_base, growth_rate)
ACCOUNTS = [
    ("product_sales",      "revenue", "sales",      2_400_000.0, 0.012),
    ("services",           "revenue", "sales",        800_000.0, 0.010),
    ("consulting",         "revenue", "sales",        460_000.0, 0.008),
    ("subscriptions",      "revenue", "marketing",    680_000.0, 0.014),
    ("licensing",          "revenue", "marketing",    260_000.0, 0.009),
    ("events",             "revenue", "marketing",    170_000.0, 0.005),
    ("cost_of_goods",      "cogs",    "operations", 1_450_000.0, 0.010),
    ("cloud_infrastructure","cogs",   "operations",   300_000.0, 0.013),
    ("fulfillment",        "cogs",    "operations",   230_000.0, 0.009),
    ("salaries",           "opex",    "operations", 1_050_000.0, 0.006),
    ("benefits",           "opex",    "operations",   210_000.0, 0.006),
    ("rent",               "opex",    "operations",   150_000.0, 0.000),
    ("utilities",          "opex",    "operations",    38_000.0, 0.002),
    ("insurance",          "opex",    "operations",    45_000.0, 0.001),
    ("marketing_spend",    "opex",    "marketing",    185_000.0, 0.009),
    ("sales_commission",   "opex",    "sales",         96_000.0, 0.012),
    ("travel",             "opex",    "sales",         42_000.0, 0.006),
    ("rnd_equipment",      "opex",    "rnd",           88_000.0, 0.007),
    ("software_tools",     "opex",    "rnd",           64_000.0, 0.012),
    ("professional_fees",  "opex",    "rnd",           52_000.0, 0.005),
    ("training",           "opex",    "rnd",           26_000.0, 0.004),
    ("depreciation",       "opex",    "rnd",           74_000.0, 0.000),
]

# month-of-year multiplier: summer dip, year-end push (0 = January)
SEASONALITY = {0: 1.00, 1: 1.00, 2: 1.02, 3: 1.01, 4: 1.03, 5: 1.00,
               6: 0.94, 7: 0.96, 8: 1.04, 9: 1.06, 10: 1.15, 11: 1.10}


def build_dataframes(seed: int = SEED) -> dict[str, pd.DataFrame]:
    """Return the five star-schema frames (deterministic)."""
    rng = np.random.default_rng(seed)
    months = pd.period_range(START, periods=N_MONTHS, freq="M")

    dim_date = pd.DataFrame({
        "month_id": np.arange(1, N_MONTHS + 1),
        "month": months.to_timestamp(),
        "month_name": months.strftime("%B"),
        "month_num": months.month,
        "quarter": months.quarter,
        "year": months.year,
    })

    dim_department = pd.DataFrame({
        "dept_id": np.arange(1, len(DEPARTMENTS) + 1),
        "department_name": DEPARTMENTS,
    })

    dim_account = pd.DataFrame({
        "account_id": np.arange(1, len(ACCOUNTS) + 1),
        "account_name": [a[0] for a in ACCOUNTS],
        "category": [a[1] for a in ACCOUNTS],
        "owner_department": [a[2] for a in ACCOUNTS],
    })

    dept_id = {name: i + 1 for i, name in enumerate(DEPARTMENTS)}

    rows_gl, rows_budget = [], []
    for i, period in enumerate(months):
        month_of_year = period.month - 1
        for (name, category, owner, base, growth), account_id in zip(
                ACCOUNTS, np.arange(1, len(ACCOUNTS) + 1)):
            trend = (1 + growth) ** i
            seasonal = SEASONALITY[month_of_year]
            actual = base * trend * seasonal * rng.normal(1.0, 0.06)
            budget = actual * rng.normal(1.0, 0.04)
            rows_gl.append({"month_id": i + 1, "dept_id": dept_id[owner],
                            "account_id": int(account_id),
                            "actual": round(float(actual), 2)})
            rows_budget.append({"month_id": i + 1, "dept_id": dept_id[owner],
                                "account_id": int(account_id),
                                "budget": round(float(budget), 2)})

    fact_gl = pd.DataFrame(rows_gl)
    fact_budget = pd.DataFrame(rows_budget)

    return {"dim_date": dim_date, "dim_department": dim_department,
            "dim_account": dim_account, "fact_gl": fact_gl,
            "fact_budget": fact_budget}
