import pytest

from finance_llm.sqlgen import build_sql, validate_sql


def _plan(metric="revenue", time=None, dims=None, compare=None, filters=None,
          top_n=None):
    return {"metric": metric, "dims": dims or [], "time": time,
            "compare": compare, "filters": filters or [], "top_n": top_n}


def test_build_revenue_year():
    sql = build_sql(_plan(time={"type": "year", "value": 2025}))
    assert sql.startswith("SELECT")
    assert "a.category = 'revenue'" in sql
    assert "dt.year = 2025" in sql


def test_build_group_by_department():
    sql = build_sql(_plan(metric="opex", dims=["department"],
                          time={"type": "year", "value": 2024}))
    assert "GROUP BY d.department_name" in sql


def test_build_variance_joins_budget():
    sql = build_sql(_plan(metric="variance"))
    assert "fact_budget b" in sql
    assert "SUM(f.actual) - SUM(b.budget)" in sql


def test_build_attainment():
    sql = build_sql(_plan(metric="attainment"))
    assert "* 100.0" in sql
    assert "NULLIF" in sql


def test_build_gross_profit_case():
    sql = build_sql(_plan(metric="gross_profit"))
    assert "CASE WHEN a.category = 'revenue'" in sql


def test_build_top_n():
    sql = build_sql(_plan(dims=["account"], top_n=5))
    assert "LIMIT 5" in sql
    assert "ORDER BY SUM(f.actual) DESC" in sql


def test_unknown_metric_raises():
    with pytest.raises(ValueError):
        build_sql(_plan(metric="unknown"))


VALID = [
    "SELECT SUM(f.actual) AS revenue FROM fact_gl f JOIN dim_account a ON "
    "f.account_id = a.account_id JOIN dim_date dt ON f.month_id = dt.month_id "
    "WHERE a.category = 'revenue' AND dt.year = 2025",
    "SELECT d.department_name AS department, SUM(f.actual) AS opex FROM "
    "fact_gl f JOIN dim_account a ON f.account_id = a.account_id JOIN "
    "dim_department d ON f.dept_id = d.dept_id JOIN dim_date dt ON "
    "f.month_id = dt.month_id WHERE a.category = 'opex' AND dt.year = 2024 "
    "GROUP BY d.department_name",
    build_sql(_plan(metric="variance", time={"type": "month", "value": 2025, "month": 11})),
    build_sql(_plan(metric="attainment", time={"type": "year", "value": 2025})),
]

INVALID = [
    "DROP TABLE fact_gl",
    "SELECT * FROM fact_gl; DROP TABLE fact_gl",
    "SELECT SUM(actual) FROM fact_gl -- comment",
    "SELECT 1 UNION SELECT 2",
    "SELECT * FROM information_schema.tables",
    "INSERT INTO fact_gl VALUES (1, 2, 3, 4)",
    "DELETE FROM fact_gl",
    "UPDATE fact_gl SET actual = 0",
    "ALTER TABLE fact_gl ADD COLUMN hacker TEXT",
    "SELECT * FROM pragma_table_info('fact_gl')",
    "ATTACH 'evil.db'",
    "SELECT * FROM fact_gl WHERE 1=1 /* x */",
    "SELECT SUM(f.actual FROM fact_gl",
    "SELECT SUM(f.actual)) FROM fact_gl",
    "SELECT f.actual, h.secret FROM fact_gl f JOIN evil h ON 1=1",
    "SELECT f.actual FROM fact_gl f WHERE f.actual > (SELECT MAX(actual) FROM fact_gl)",
]


@pytest.mark.parametrize("sql", VALID)
def test_validate_accepts(sql):
    assert validate_sql(sql), f"should accept: {sql}"


@pytest.mark.parametrize("sql", INVALID)
def test_validate_rejects(sql):
    assert not validate_sql(sql), f"should reject: {sql}"


def test_validate_rejects_non_select():
    assert not validate_sql("WITH x AS (SELECT 1) SELECT * FROM x")


def test_validate_empty_and_weird():
    assert not validate_sql("")
    assert not validate_sql(None)
    assert not validate_sql("SELECT")
