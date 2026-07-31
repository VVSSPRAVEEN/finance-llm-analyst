import pytest

from finance_llm.answers import ask
from finance_llm.warehouse import Warehouse


@pytest.fixture
def wh(tmp_path):
    w = Warehouse(tmp_path / "test.db")
    w.build(force=True)
    yield w
    w.close()


class FakeLLM:
    def __init__(self, sql=None):
        self.sql = sql
        self.available = True

    def translate(self, question, schema_text):
        return self.sql


def test_ask_revenue_rules(wh):
    result = ask(wh, "total revenue in 2025")
    assert result["source"] == "rules"
    assert result["metric"] == "revenue"
    assert "$" in result["answer"]
    assert float(result["answer"].split("$")[1].replace(",", "")) > 0


def test_ask_unknown_question(wh):
    result = ask(wh, "what is the meaning of life")
    assert result["metric"] == "unknown"
    assert "Try e.g." in result["answer"]


def test_ask_growth(wh):
    result = ask(wh, "revenue growth year over year")
    assert "%" in result["answer"]
    assert "vs previous period" in result["answer"]


def test_ask_variance_vs_budget(wh):
    result = ask(wh, "revenue vs budget in 2025")
    assert result["metric"] == "revenue"
    assert "vs budget" in result["answer"].lower()


def test_ask_attainment(wh):
    result = ask(wh, "budget attainment for sales in 2024")
    assert "%" in result["answer"]


def test_ask_by_department_table(wh):
    result = ask(wh, "opex by department in Q3 2024")
    assert result["table"] is not None
    assert "|" in result["table"]


def test_ask_llm_valid_sql(wh):
    llm = FakeLLM("SELECT SUM(f.actual) AS revenue FROM fact_gl f "
                  "JOIN dim_account a ON f.account_id = a.account_id "
                  "JOIN dim_date dt ON f.month_id = dt.month_id "
                  "WHERE a.category = 'revenue' AND dt.year = 2025")
    result = ask(wh, "total revenue in 2025", llm=llm, use_llm=True)
    assert result["source"] == "llm"


def test_ask_llm_garbage_falls_back(wh):
    llm = FakeLLM("sure, here's the answer: $42")
    result = ask(wh, "total revenue in 2025", llm=llm, use_llm=True)
    assert result["source"] == "rules"


def test_ask_llm_injection_rejected(wh):
    llm = FakeLLM("SELECT * FROM fact_gl; DROP TABLE fact_gl")
    result = ask(wh, "total revenue in 2025", llm=llm, use_llm=True)
    assert result["source"] == "rules"
    # warehouse must be untouched
    assert wh.query("SELECT COUNT(*) AS n FROM fact_gl")["n"][0] == 792


def test_ask_llm_execution_error_falls_back(wh):
    llm = FakeLLM("SELECT SUM(f.actual) AS revenue FROM fact_gl f "
                  "JOIN dim_account a ON f.account_id = a.account_id "
                  "WHERE a.category = 'revenue' AND dt.year = 2025 AND "
                  "f.unknown_column > 0")
    result = ask(wh, "total revenue in 2025", llm=llm, use_llm=True)
    assert result["source"] == "rules"
