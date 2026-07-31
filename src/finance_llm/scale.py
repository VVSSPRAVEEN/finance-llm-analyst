"""Big-data generation: multi-gigabyte transaction fact table.

Generates a >5GB transaction-level fact table into
`data/transactions.parquet` (gitignored) via DuckDB streaming COPY.
Row count is probe-calibrated to exceed `--target-gb`.

Usage:
    python -m finance_llm.scale --target-gb 5.2 [--out data]
"""
from __future__ import annotations

import argparse
import pathlib

import duckdb

SQL_FMT = (
    "SELECT i AS txn_id,"
    "       date '2023-01-01' + (i % 1096) AS txn_date,"
    "       (i % 22) + 1 AS account_id,"
    "       (i % 4) + 1 AS dept_id,"
    "       round(((i % 89) * 321.75 + (i % 7) * 12.5), 2) AS amount,"
    "       list_value('revenue','cogs','opex')[i % 3] AS txn_type,"
    "       chr(65 + (i % 4)) AS region"
    "  FROM range({n}) t(i)"
)


def generate(target_gb: float = 5.2, out_dir: str = "data",
             seed: int = 42, probe_rows: int = 5_000_000) -> dict:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target_bytes = int(target_gb * 1_000_000_000)
    conn = duckdb.connect()
    conn.execute(f"SELECT setseed({seed})")

    probe_path = out / "_probe.parquet"
    conn.execute(f"COPY ({SQL_FMT.format(n=probe_rows)}) "
                 f"TO '{probe_path.as_posix()}' (FORMAT PARQUET)")
    bytes_per_probe_row = probe_path.stat().st_size / probe_rows
    probe_path.unlink()

    rows = max(1, int(target_bytes / bytes_per_probe_row))
    target = out / "transactions.parquet"
    conn.execute(f"COPY ({SQL_FMT.format(n=rows)}) "
                 f"TO '{target.as_posix()}' (FORMAT PARQUET)")
    size = target.stat().st_size
    result = {"file": str(target), "rows": rows,
              "size_gb": round(size / 1e9, 2), "target_gb": target_gb}
    print(f"Generated {result['rows']:,} rows -> {result['size_gb']} GB "
          f"({result['file']})")
    if size < target_bytes * 0.95:
        raise SystemExit(f"ERROR: {result['size_gb']} GB < target {target_gb} GB")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate big transaction data")
    parser.add_argument("--target-gb", type=float, default=5.2)
    parser.add_argument("--out", default="data")
    args = parser.parse_args(argv)
    generate(args.target_gb, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
