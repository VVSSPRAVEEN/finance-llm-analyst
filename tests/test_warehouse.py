from finance_llm.warehouse import TABLE_NAMES, Warehouse


def test_build_and_counts(tmp_path):
    wh = Warehouse(tmp_path / "test.db")
    wh.build(force=True)
    for name in TABLE_NAMES:
        count = wh.query(f"SELECT COUNT(*) AS n FROM {name}")["n"][0]
        assert count > 0
    v_pnl = wh.query("SELECT COUNT(*) AS n FROM v_pnl")
    assert v_pnl["n"][0] == 36
    wh.close()


def test_pnl_consistency(tmp_path):
    wh = Warehouse(tmp_path / "test.db")
    wh.build(force=True)
    row = wh.query("SELECT * FROM v_pnl ORDER BY month LIMIT 1").iloc[0]
    assert row["gross_profit"] == row["revenue"] - row["cogs"]
    assert row["operating_profit"] == row["revenue"] - row["cogs"] - row["opex"]
    assert row["revenue"] > row["cogs"] > 0
    wh.close()


def test_schema_metadata(tmp_path):
    wh = Warehouse(tmp_path / "test.db")
    wh.build(force=True)
    meta = wh.schema_metadata()
    assert set(meta["tables"]) == set(TABLE_NAMES)
    assert "sales" in meta["departments"]
    assert "revenue" in meta["account_categories"]
    assert meta["first_month"] == "2023-01-01"
    assert meta["last_month"] == "2025-12-01"
    wh.close()


def test_rebuild_idempotent(tmp_path):
    wh = Warehouse(tmp_path / "test.db")
    wh.build(force=True)
    wh.build(force=True)
    n = wh.query("SELECT COUNT(*) AS n FROM fact_gl")["n"][0]
    assert n == 792
    wh.close()
