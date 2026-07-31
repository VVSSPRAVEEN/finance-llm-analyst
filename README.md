# Finance LLM Analyst

Ask financial questions in plain English; get answers from a DuckDB
warehouse — via a deterministic rule engine, or an LLM whose SQL is
**hard-validated against a whitelist** before execution. Ships with a
prompt-tuning harness that picks the best few-shot prompt variant.

## Architecture

```
question ──► rule engine ──► plan ──► whitelist SQL ──► DuckDB ──► answer + table
    │            ▲  (offline, deterministic)
    └── LLM ─────┘  (validated: SELECT-only, whitelist tables/columns)
```

| Module | Role |
|---|---|
| `generate` | Synthetic star schema: 22 accounts (revenue/cogs/opex), 4 departments, 36 months (2023-2025), actuals + budget (792 rows/fact), seeded 42 |
| `warehouse` | DuckDB build, `v_pnl` monthly P&L view, schema metadata |
| `rules` | NL -> plan: metrics, time ranges, dimensions, filters, top-N, comparisons |
| `sqlgen` | Whitelist-only SQL builder + `validate_sql` gatekeeper (rejects DDL/DML/UNION/comments/unknown identifiers) |
| `answers` | Plan execution, growth/variance math, human answer + markdown table |
| `llm` | Anthropic (or Gemini) NL->SQL with few-shot prompt; any failure degrades to rules |
| `tuning` | Prompt-tuning harness: 4 prompt variants x 14 golden questions, offline scores + optional live LLM scoring |

## Quick start

```bash
pip install -r requirements.txt
python -m finance_llm.cli init        # builds finance.db
python -m finance_llm.cli ask "total revenue in 2025"
python -m finance_llm.cli ask "opex by department in Q3 2024"
python -m finance_llm.cli ask "revenue vs budget last month"
pytest
```

## LLM mode (optional)

Copy `.env.example` to `.env`, add one API key (Anthropic preferred,
Gemini fallback), then:

```bash
python -m finance_llm.cli ask "gross profit in 2024" --llm
python -m finance_llm.cli repl --llm
```

The LLM's SQL passes through `validate_sql`; anything non-whitelist is
silently discarded and the rule engine answers instead. **`.env` is
gitignored — keys never leave your machine.**

## Prompt tuning

```bash
python -m finance_llm.cli tune            # offline variant scoring
python -m finance_llm.cli tune --live     # + real LLM scoring (uses API)
```

Writes `docs/prompt_tuning_report.md` + `docs/prompt_selection.json`
with the winning variant and per-variant scores (parse rate, plan
accuracy, SQL validity, domain coverage).

## Security model

`sqlgen.validate_sql` is the only door: SELECT-only, five whitelisted
tables, whitelisted columns, no semicolons/comments/UNION/DDL/DML, no
unknown identifiers. Injection attempts (`DROP TABLE`, stacked queries,
`information_schema`) are rejected by unit tests.

## Big-data mode

```bash
python -m finance_llm.cli scale --target-gb 6   # generates ~6GB parquet under data/ (gitignored)
```

`scale` materializes a multi-hundred-million-row transaction fact table
so the project ships with 5GB+ of real queryable data while the git
repo stays lean (GitHub hard-caps repos at 5GB).
