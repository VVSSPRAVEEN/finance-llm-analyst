"""Finance LLM Analyst — NL-to-SQL over a synthetic financial warehouse.

Pipeline: natural language -> rule engine (or LLM with validation) ->
whitelist-only SQL -> DuckDB -> formatted answer + markdown table.
Includes a prompt-tuning harness for few-shot prompt selection.
"""
from finance_llm.answers import ask, format_answer
from finance_llm.rules import parse_question
from finance_llm.sqlgen import build_sql, validate_sql
from finance_llm.warehouse import Warehouse

__all__ = ["ask", "format_answer", "parse_question", "build_sql",
           "validate_sql", "Warehouse"]
