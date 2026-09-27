from pathlib import Path

import json

from collector.cli import _filter_resume, _order_oldest_first
from collector.repo_ref import RepoRef


def _make_ref(owner: str, name: str) -> RepoRef:
    return RepoRef(owner=owner, name=name, clone_url=f"ssh://x/{owner}/{name}.git")


def test_filter_resume_skips_repos_with_existing_latest_json(tmp_path: Path):
    output_dir = tmp_path / "output"
    done_ref = _make_ref("acme", "done")
    pending_ref = _make_ref("acme", "pending")

    done_dir = output_dir / done_ref.workdir_name
    done_dir.mkdir(parents=True)
    (done_dir / "latest.json").write_text("{}", encoding="utf-8")

    remaining, skipped = _filter_resume([done_ref, pending_ref], output_dir)

    assert remaining == [pending_ref]
    assert skipped == 1


def test_filter_resume_keeps_everything_when_output_dir_is_empty(tmp_path: Path):
    refs = [_make_ref("acme", "a"), _make_ref("acme", "b")]
    remaining, skipped = _filter_resume(refs, tmp_path / "nonexistent-output")

    assert remaining == refs
    assert skipped == 0


def _write_latest(output_dir: Path, ref: RepoRef, collected_at: str) -> None:
    repo_dir = output_dir / ref.workdir_name
    repo_dir.mkdir(parents=True)
    record = {"collection": {"collected_at": collected_at}}
    (repo_dir / "latest.json").write_text(json.dumps(record), encoding="utf-8")


def test_order_oldest_first_puts_new_repos_first_then_stalest(tmp_path: Path):
    output_dir = tmp_path / "output"
    fresh, stale, new_a, new_b = (_make_ref("acme", n) for n in ("fresh", "stale", "new-a", "new-b"))
    _write_latest(output_dir, fresh, "2026-09-21T10:00:00+00:00")
    _write_latest(output_dir, stale, "2026-09-19T10:00:00+00:00")

    ordered = _order_oldest_first([fresh, new_a, stale, new_b], output_dir)

    assert ordered == [new_a, new_b, stale, fresh]


def test_order_oldest_first_treats_unreadable_latest_json_as_new(tmp_path: Path):
    output_dir = tmp_path / "output"
    fresh, broken = _make_ref("acme", "fresh"), _make_ref("acme", "broken")
    _write_latest(output_dir, fresh, "2026-09-21T10:00:00+00:00")
    (output_dir / broken.workdir_name).mkdir(parents=True)
    (output_dir / broken.workdir_name / "latest.json").write_text("not json", encoding="utf-8")

    assert _order_oldest_first([fresh, broken], output_dir) == [broken, fresh]
