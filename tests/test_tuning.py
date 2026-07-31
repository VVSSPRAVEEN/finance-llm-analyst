import json

from finance_llm.tuning import GOLDEN, VARIANTS, evaluate_variant, run_tuning


def test_golden_set_parses():
    from finance_llm.rules import parse_question
    for g in GOLDEN:
        plan = parse_question(g["q"])
        assert plan["metric"] == g["metric"], f"{g['q']} -> {plan['metric']}"
        assert set(plan["dims"]) == set(g.get("dims", [])), g["q"]


def test_evaluate_variant_shape():
    result = evaluate_variant(VARIANTS[0], golden=GOLDEN[:4])
    assert set(result) >= {"name", "parse_rate", "plan_acc", "sql_ok",
                           "coverage", "live_acc", "score"}
    assert 0 <= result["score"] <= 1.1


def test_scores_sorted_desc(tmp_path):
    out = run_tuning(out_dir=tmp_path)
    scores = [r["score"] for r in out["results"]]
    assert scores == sorted(scores, reverse=True)


def test_run_tuning_writes_files(tmp_path):
    out = run_tuning(out_dir=tmp_path)
    assert out["winner"]["name"] in {v["name"] for v in VARIANTS}
    assert (tmp_path / "prompt_tuning_report.md").exists()
    assert (tmp_path / "prompt_selection.json").exists()
    selection = json.loads((tmp_path / "prompt_selection.json").read_text(encoding="utf-8"))
    assert selection["winner"]["name"] == out["winner"]["name"]


def test_offline_live_disabled():
    # without a key, live scoring must be zero and never call the network
    result = evaluate_variant(VARIANTS[0], golden=GOLDEN[:2], llm=None, live=False)
    assert result["live_acc"] == 0.0
