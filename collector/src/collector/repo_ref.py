"""Identifies one repository to collect data for, across all three sources
(git clone URL, owner/name for the platform API, gitRepo id/uuid for AppSec).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str
    clone_url: str
    gitrepo_id: str | None = None  # AppSec `gitRepo` query param; None => skip security category

    @property
    def full_path(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def workdir_name(self) -> str:
        return f"{self.owner}__{self.name}"


def load_repo_refs(path: Path) -> list[RepoRef]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return [
        RepoRef(
            owner=entry["owner"],
            name=entry["name"],
            clone_url=entry["clone_url"],
            gitrepo_id=entry.get("gitrepo_id"),
        )
        for entry in raw.get("repos", [])
    ]
