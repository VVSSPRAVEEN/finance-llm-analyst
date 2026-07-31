from finance_llm.rules import parse_question


def test_revenue_year():
    p = parse_question("total revenue in 2025")
    assert p["metric"] == "revenue"
    assert p["time"] == {"type": "year", "value": 2025}
    assert p["dims"] == []


def test_opex_quarter():
    p = parse_question("how much did we spend on opex in q4 2024")
    assert p["metric"] == "opex"
    assert p["time"] == {"type": "quarter", "value": 2024, "quarter": 4}


def test_revenue_by_department():
    p = parse_question("revenue by department for 2024")
    assert p["metric"] == "revenue"
    assert p["dims"] == ["department"]
    assert p["time"] == {"type": "year", "value": 2024}


def test_gross_profit_last_month():
    p = parse_question("gross profit last month")
    assert p["metric"] == "gross_profit"
    assert p["time"] == {"type": "last_month"}


def test_cogs_monthly():
    p = parse_question("cogs by month in 2023")
    assert p["metric"] == "cogs"
    assert p["dims"] == ["month"]
    assert p["time"] == {"type": "year", "value": 2023}


def test_attainment_dept_filter():
    p = parse_question("budget attainment for sales in 2024")
    assert p["metric"] == "attainment"
    assert {"field": "department", "value": "sales"} in p["filters"]


def test_marketing_spend_alias():
    p = parse_question("marketing spend ytd")
    assert p["metric"] == "opex"
    assert {"field": "account", "value": "marketing_spend"} in p["filters"]
    assert p["time"]["type"] == "ytd"


def test_growth_compare():
    p = parse_question("revenue growth year over year")
    assert p["metric"] == "revenue"
    assert p["compare"]["type"] == "growth"


def test_top_n_accounts():
    p = parse_question("top 5 revenue accounts in 2025")
    assert p["metric"] == "revenue"
    assert p["top_n"] == 5
    assert p["dims"] == ["account"]


def test_salaries_by_department():
    p = parse_question("salaries by department in 2024")
    assert p["metric"] == "opex"
    assert p["dims"] == ["department"]
    assert {"field": "account", "value": "salaries"} in p["filters"]


def test_quarterly_trend():
    p = parse_question("quarterly opex trend in 2025")
    assert p["metric"] == "opex"
    assert p["dims"] == ["quarter"]


def test_unknown_question():
    p = parse_question("what is the meaning of life")
    assert p["metric"] == "unknown"
