"""Flattens every output/<owner>__<name>/latest.json into one CSV, one row
per repo. Needs pandas, which is NOT a collector dependency (the collector
itself never needs a dataframe library) -- run it via:

    uv run --extra export python scripts/export_csv.py [output_csv_path]

Defaults to writing repo_health_report.csv next to this script's project root.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "repo_health_report.csv"

# A single git error can print one line per file (seen live on a Windows
# MAX_PATH failure: 33k+ characters) -- the collector itself now caps this at
# the source (git_client.py), but cap again here too so a report generated
# from older JSON files stays readable in a spreadsheet.
_MAX_CELL_CHARS = 2000


def _flatten_value(value):
    if isinstance(value, (list, dict)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        return value
    if len(text) > _MAX_CELL_CHARS:
        text = text[:_MAX_CELL_CHARS] + f"... [truncated, {len(text)} chars total]"
    return text


def build_dataframe(output_dir: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(glob.glob(str(output_dir / "*" / "latest.json"))):
        with open(path, encoding="utf-8") as fh:
            rows.append(json.load(fh))
    if not rows:
        raise SystemExit(f"no latest.json files found under {output_dir}")
    return records_to_dataframe(rows)


def records_to_dataframe(rows: list[dict]) -> pd.DataFrame:
    """One flattened CSV row per collector record (see build_dataframe)."""
    df = pd.json_normalize(rows, sep=".")
    for col in df.columns:
        df[col] = df[col].apply(_flatten_value)

    lead_cols = ["repo.full_path", "repo.visibility", "repo.url", "repo.description"]
    other_cols = [c for c in df.columns if c not in lead_cols]
    return df[lead_cols + other_cols]


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    # same variable the collector writes to; relative paths are taken from the project root
    df = build_dataframe(PROJECT_ROOT / os.getenv("COLLECTOR_OUTPUT_DIR", "output"))
    df.to_csv(out_path, index=False, encoding="utf-8-sig")  # BOM so Excel opens Cyrillic correctly
    print(f"wrote {len(df)} rows x {len(df.columns)} cols -> {out_path}")


if __name__ == "__main__":
    main()
