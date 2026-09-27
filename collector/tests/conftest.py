from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def local_source_repo(tmp_path: Path) -> Path:
    """A tiny real git repo on disk, used as a `clone_url` so the git-native
    collectors can be exercised with zero network access.
    """
    repo_dir = tmp_path / "source_repo"
    repo_dir.mkdir()
    _git(["init", "-q", "-b", "main"], repo_dir)
    _git(["config", "user.email", "test@example.com"], repo_dir)
    _git(["config", "user.name", "Test User"], repo_dir)

    (repo_dir / "README.md").write_text(
        "# Demo\n\n## Installation\n\npip install demo\n\n## License\n\nSee LICENSE.\n", encoding="utf-8"
    )
    (repo_dir / "LICENSE").write_text("MIT License\n\nPermission is hereby granted, free of charge...\n", encoding="utf-8")
    (repo_dir / "CONTRIBUTING.md").write_text("Please open a pull request.\n", encoding="utf-8")

    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text(
        "# TODO: refactor this module\ndef main():\n    pass\n# FIXME: handle errors properly\n",
        encoding="utf-8",
    )

    sourcecraft_dir = repo_dir / ".sourcecraft"
    sourcecraft_dir.mkdir()
    (sourcecraft_dir / "ci.yaml").write_text(
        "stages:\n  - test\n  - lint\n  - deploy\n", encoding="utf-8"
    )

    _git(["add", "-A"], repo_dir)
    _git(["commit", "-q", "-m", "initial commit"], repo_dir)

    return repo_dir


@pytest.fixture
def empty_source_repo(tmp_path: Path) -> Path:
    """A git repo with zero commits -- `git clone` of this succeeds, but
    HEAD doesn't resolve to a real commit, which found a real bug live: any
    caller assuming HEAD is valid (`ls-tree HEAD`, `log`) crashed the whole
    repo's processing instead of degrading gracefully. Plenty of real
    public repos are genuinely this empty (fresh test/hackathon placeholders).
    """
    repo_dir = tmp_path / "empty_repo"
    repo_dir.mkdir()
    _git(["init", "-q", "-b", "main"], repo_dir)
    return repo_dir
