"""Collects one repo and upserts its row into the existing CSV report. This is
what the backend's on-demand analysis runs (COLLECTOR_COMMAND gets only
`{full_path}`):

    uv run --project collector --extra export python collector/scripts/collect_one.py {full_path}

Unlike export_csv.py it never rebuilds the CSV from output/: a server that has
collected only a handful of repos locally would otherwise shrink the
27k-row report down to those few. Only the one row is replaced (or added);
the file is swapped in atomically so the backend never reads half a CSV.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from collector.cli import main as collector_main  # noqa: E402
from collector.config import load_settings  # noqa: E402
from export_csv import records_to_dataframe  # noqa: E402

DEFAULT_CSV = PROJECT_ROOT.parent / "repo_health_report.csv"
CLONE_URL = "https://git.sourcecraft.dev/{owner}/{name}.git"


def upsert_row(csv_path: Path, record: dict) -> int:
    new_row = records_to_dataframe([record])
    full_path = record["repo"]["full_path"]
    if csv_path.exists():
        report = pd.read_csv(csv_path, encoding="utf-8-sig", low_memory=False)
        report = report[report["repo.full_path"] != full_path]
        # keep the report's column order, append any column only this record has
        columns = list(report.columns) + [c for c in new_row.columns if c not in report.columns]
        report = pd.concat([report, new_row], ignore_index=True)[columns]
    else:
        report = new_row
    tmp_path = csv_path.with_name(csv_path.name + ".tmp")
    report.to_csv(tmp_path, index=False, encoding="utf-8-sig")
    os.replace(tmp_path, csv_path)
    return len(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("full_path", help="owner/name, as the backend passes it")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="report to update (default: repo root)")
    args = parser.parse_args()

    owner, sep, name = args.full_path.strip("/").partition("/")
    if not sep or not owner or not name:
        parser.error(f"expected owner/name, got {args.full_path!r}")
    csv_path = args.csv.resolve()

    # the collector's output/ and .workdir are relative to the cwd -- keep them inside collector/
    os.chdir(PROJECT_ROOT)
    code = collector_main([
        "collect", "--owner", owner, "--name", name,
        "--clone-url", CLONE_URL.format(owner=owner, name=name),
    ])
    if code != 0:
        return code

    latest = load_settings().output_dir / f"{owner}__{name}" / "latest.json"
    record = json.loads(latest.read_text(encoding="utf-8"))
    rows = upsert_row(csv_path, record)
    print(f"[{args.full_path}] row updated -> {csv_path} ({rows} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
