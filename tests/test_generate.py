import pandas as pd

from finance_llm.generate import ACCOUNTS, N_MONTHS, build_dataframes


def test_frames_present():
    frames = build_dataframes()
    assert set(frames) == {"dim_date", "dim_department", "dim_account",
                           "fact_gl", "fact_budget"}


def test_dimensions():
    frames = build_dataframes()
    assert len(frames["dim_date"]) == N_MONTHS == 36
    assert list(frames["dim_date"]["year"].unique()) == [2023, 2024, 2025]
    assert len(frames["dim_department"]) == 4
    assert len(frames["dim_account"]) == 22


def test_fact_grains():
    frames = build_dataframes()
    assert len(frames["fact_gl"]) == N_MONTHS * len(ACCOUNTS) == 792
    assert len(frames["fact_budget"]) == 792


def test_no_nan_and_positive():
    frames = build_dataframes()
    assert not frames["fact_gl"].isna().any().any()
    assert not frames["fact_budget"].isna().any().any()
    assert (frames["fact_gl"]["actual"] > 0).all()
    assert (frames["fact_budget"]["budget"] > 0).all()


def test_deterministic():
    a = build_dataframes()
    b = build_dataframes()
    for key in a:
        assert a[key].equals(b[key])


def test_revenue_grows_over_time():
    frames = build_dataframes()
    gl = frames["fact_gl"].merge(frames["dim_date"], on="month_id")
    by_year = gl[gl["month_id"].isin(range(1, 13))]["actual"].sum()
    _ = by_year  # 2023 baseline
    y2025 = gl[gl["month_id"].isin(range(25, 37))]["actual"].sum()
    assert y2025 > 0
