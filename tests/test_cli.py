from finance_llm.cli import main


def test_cli_init(tmp_path, capsys):
    db = str(tmp_path / "finance.db")
    assert main(["init", "--db", db]) == 0
    assert (tmp_path / "finance.db").exists()
    out = capsys.readouterr().out
    assert "Warehouse ready" in out


def test_cli_ask(tmp_path, capsys):
    db = str(tmp_path / "finance.db")
    main(["init", "--db", db])
    assert main(["ask", "total revenue in 2025", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "Revenue:" in out
    assert "(source: rules)" in out


def test_cli_ask_table(tmp_path, capsys):
    db = str(tmp_path / "finance.db")
    main(["init", "--db", db])
    main(["ask", "opex by department in Q3 2024", "--db", db])
    out = capsys.readouterr().out
    assert "department" in out


def test_cli_eval_all_golden_pass(tmp_path):
    db = str(tmp_path / "finance.db")
    main(["init", "--db", db])
    assert main(["eval", "--db", db]) == 0


def test_cli_tune(tmp_path):
    out = str(tmp_path / "docs")
    assert main(["tune", "--out", out]) == 0
    assert (tmp_path / "docs" / "prompt_tuning_report.md").exists()


def test_cli_all(tmp_path, capsys):
    db = str(tmp_path / "all.db")
    assert main(["all", "--db", db, "--force"]) == 0
    out = capsys.readouterr().out
    assert "Revenue:" in out
    assert "Winner:" in out
