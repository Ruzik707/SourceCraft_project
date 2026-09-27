from __future__ import annotations

import json
from pathlib import Path

from .repo_ref import RepoRef


def write_record(record: dict, repo_ref: RepoRef, output_dir: Path) -> tuple[Path, Path]:
    """Writes both a timestamped snapshot and a `latest.json` pointer file,
    so downstream consumers (scoring service, dashboard) can always read the
    newest run without knowing the run's timestamp.
    """
    repo_dir = output_dir / repo_ref.workdir_name
    repo_dir.mkdir(parents=True, exist_ok=True)

    collected_at = record["collection"]["collected_at"].replace(":", "").replace("+00:00", "Z")
    snapshot_path = repo_dir / f"{collected_at}.json"
    latest_path = repo_dir / "latest.json"

    payload = json.dumps(record, indent=2, ensure_ascii=False, sort_keys=False)
    snapshot_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")
    return snapshot_path, latest_path
