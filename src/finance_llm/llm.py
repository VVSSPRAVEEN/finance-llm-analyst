"""LLM client for NL -> SQL with hard validation.

Provider-agnostic: reads `.env` (ANTHROPIC_API_KEY preferred, then
GEMINI_API_KEY). SDK imports are lazy so the package works fully
offline; any provider error degrades to None -> rule-engine fallback.
All returned SQL is passed through `sqlgen.validate_sql` before use.
"""
from __future__ import annotations

import os
import pathlib
import re

from finance_llm.sqlgen import validate_sql

FEW_SHOT = [
    ("What was total revenue in 2025?",
     "SELECT SUM(f.actual) AS revenue FROM fact_gl f "
     "JOIN dim_account a ON f.account_id = a.account_id "
     "JOIN dim_date dt ON f.month_id = dt.month_id "
     "WHERE a.category = 'revenue' AND dt.year = 2025"),
    ("Show opex by department for 2024.",
     "SELECT d.department_name AS department, SUM(f.actual) AS opex "
     "FROM fact_gl f "
     "JOIN dim_account a ON f.account_id = a.account_id "
     "JOIN dim_department d ON f.dept_id = d.dept_id "
     "JOIN dim_date dt ON f.month_id = dt.month_id "
     "WHERE a.category = 'opex' AND dt.year = 2024 "
     "GROUP BY d.department_name"),
    ("Revenue vs budget last month.",
     "SELECT SUM(f.actual) - SUM(b.budget) AS variance "
     "FROM fact_gl f "
     "JOIN fact_budget b ON f.month_id = b.month_id AND "
     "f.dept_id = b.dept_id AND f.account_id = b.account_id "
     "JOIN dim_account a ON f.account_id = a.account_id "
     "JOIN dim_date dt ON f.month_id = dt.month_id "
     "WHERE a.category = 'revenue' AND dt.year = 2025 AND dt.month_num = 11"),
]


def load_env(path: str | pathlib.Path = ".env") -> dict:
    """Minimal .env parser (no external dependency)."""
    env: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


class LLMClient:
    """Wraps Anthropic (primary) or Gemini (fallback) as a translate() callable."""

    def __init__(self, env: dict | None = None, model: str | None = None):
        self.env = env if env is not None else load_env()
        key = self.env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if key:
            self.provider = "anthropic"
            self.model = model or self.env.get("LLM_MODEL", "claude-sonnet-4-5")
            self._key = key
        else:
            key = self.env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
            self.provider = "gemini" if key else None
            self.model = model or self.env.get("LLM_MODEL", "gemini-2.0-flash")
            self._key = key or ""

    @property
    def available(self) -> bool:
        return self.provider is not None

    # ------------------------------------------------------------------ api
    def translate(self, question: str, schema_text: str) -> str | None:
        """Return validated SELECT SQL for `question`, or None on failure."""
        if not self.available:
            return None
        system = ("You translate finance questions into DuckDB SQL. "
                  "Return ONLY the SQL statement, no explanation, no markdown "
                  "code fences, no trailing semicolon.\n"
                  f"Schema:\n{schema_text}\n\nExamples:\n")
        for q, sql in FEW_SHOT:
            system += f"Q: {q}\nA: {sql}\n"
        try:
            raw = self._call(system, question)
        except Exception:
            return None
        sql = self._clean(raw)
        return sql if sql and validate_sql(sql) else None

    def _clean(self, raw: str) -> str | None:
        text = raw.strip()
        m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if m:
            text = m.group(1).strip()
        if not text.upper().startswith("SELECT"):
            return None
        return text.rstrip(";")

    def _call(self, system: str, user: str) -> str:
        if self.provider == "anthropic":
            return self._call_anthropic(system, user)
        return self._call_gemini(system, user)

    def _call_anthropic(self, system: str, user: str) -> str:
        import anthropic  # lazy import

        client = anthropic.Anthropic(api_key=self._key)
        response = client.messages.create(
            model=self.model, max_tokens=1024, temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}])
        return response.content[0].text

    def _call_gemini(self, system: str, user: str) -> str:
        from google import genai  # lazy import

        client = genai.Client(api_key=self._key)
        response = client.models.generate_content(
            model=self.model,
            contents=user,
            config={"system_instruction": system, "temperature": 0})
        return response.text or ""
