"""DuckDB star-schema warehouse + query surface for the analyst.

`Warehouse.build()` creates the database file (default `finance.db`),
loads the five tables and a `v_pnl` monthly P&L view. `schema_metadata()`
exposes the whitelist + vocabulary used by the SQL generator and the LLM
prompt context.
"""
from __future__ import annotations

import pathlib

import duckdb
import pandas as pd

from finance_llm.generate import build_dataframes

TABLE_NAMES = ["dim_date", "dim_department", "dim_account", "fact_gl", "fact_budget"]

PNL_VIEW_SQL = """
CREATE OR REPLACE VIEW v_pnl AS
SELECT dt.month AS month,
       SUM(CASE WHEN a.category = 'revenue' THEN f.actual END) AS revenue,
       SUM(CASE WHEN a.category = 'cogs'    THEN f.actual END) AS cogs,
       SUM(CASE WHEN a.category = 'opex'    THEN f.actual END) AS opex,
       SUM(CASE WHEN a.category = 'revenue' THEN f.actual
                WHEN a.category = 'cogs'    THEN -f.actual END) AS gross_profit,
       SUM(CASE WHEN a.category = 'revenue' THEN f.actual
                WHEN a.category = 'cogs'    THEN -f.actual
                WHEN a.category = 'opex'    THEN -f.actual END) AS operating_profit
FROM fact_gl f
JOIN dim_account a      ON f.account_id = a.account_id
JOIN dim_date dt        ON f.month_id = dt.month_id
GROUP BY dt.month
ORDER BY dt.month
"""


class Warehouse:
    def __init__(self, db_path: str | pathlib.Path = "finance.db"):
        self.path = pathlib.Path(db_path)
        self.conn = duckdb.connect(str(self.path))

    # ------------------------------------------------------------------ build
    def build(self, force: bool = False) -> "Warehouse":
        frames = build_dataframes()
        for name in TABLE_NAMES:
            self.conn.register(f"src_{name}", frames[name])
            if force:
                self.conn.execute(f"DROP TABLE IF EXISTS {name}")
            self.conn.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM src_{name}")
        self.conn.execute("DROP VIEW IF EXISTS v_pnl")
        self.conn.execute(PNL_VIEW_SQL)
        return self

    # ------------------------------------------------------------------ query
    def query(self, sql: str) -> pd.DataFrame:
        return self.conn.execute(sql).fetch_df()

    def schema_metadata(self) -> dict:
        """Whitelist + vocabulary for SQL generation and LLM context."""
        departments = sorted(self.query("SELECT department_name FROM dim_department")["department_name"].tolist())
        accounts = sorted(self.query("SELECT account_name FROM dim_account")["account_name"].tolist())
        return {
            "tables": TABLE_NAMES,
            "departments": departments,
            "account_categories": ["revenue", "cogs", "opex"],
            "accounts": accounts,
            "first_month": str(self.query("SELECT MIN(month) AS m FROM dim_date")["m"][0].date()),
            "last_month": str(self.query("SELECT MAX(month) AS m FROM dim_date")["m"][0].date()),
        }

    def close(self) -> None:
        self.conn.close()
