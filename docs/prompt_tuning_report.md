# Prompt Tuning Report — NL to SQL

- Golden questions: 14  |  Live LLM mode: off

## Scores

| variant | parse_rate | plan_acc | sql_ok | coverage | live_acc | score |
|---|---|---|---|---|---|---|
| few_shot_rich | 1.0 | 1.0 | 0.571 | 0.857 | 0.0 | 0.864 |
| domain_context | 1.0 | 1.0 | 0.571 | 0.786 | 0.0 | 0.85 |
| chain_of_thought | 1.0 | 1.0 | 0.571 | 0.786 | 0.0 | 0.85 |
| strict_minimal | 1.0 | 1.0 | 0.571 | 0.429 | 0.0 | 0.779 |

**Winner: `few_shot_rich`** (score 0.864)

The winner maximizes domain coverage and plan accuracy. With an API key set in `.env` and FINANCE_TUNE_LIVE=1, run `python -m finance_llm.cli tune --live` for live LLM validation.
