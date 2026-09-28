"""Exercises the documentation/cicd/code_health/activity collectors against a
real (tiny, local) git repo, with platform=None and appsec=None -- these
categories must degrade gracefully with no network access, and the
git-derived facts must be correct.
"""
from __future__ import annotations

from pathlib import Path

from collector.collectors import activity, cicd, code_health, documentation
from collector.collectors.base import CollectorContext
from collector.git_client import GitRepo
from collector.repo_ref import RepoRef


def _make_ctx(local_source_repo: Path, tmp_path: Path) -> CollectorContext:
    repo_ref = RepoRef(owner="acme", name="demo", clone_url=str(local_source_repo), gitrepo_id=None)
    git_repo = GitRepo.clone(str(local_source_repo), tmp_path / "clone", shallow_since="30 days ago")
    files = git_repo.list_files()
    return CollectorContext(repo=repo_ref, git_repo=git_repo, platform=None, appsec=None, files=files)


def test_documentation_collector(local_source_repo, tmp_path):
    ctx = _make_ctx(local_source_repo, tmp_path)
    result = documentation.collect(ctx)

    assert result.status == "ok"
    assert result.data["has_readme"] is True
    assert result.data["has_license"] is True
    assert result.data["license_type"] == "MIT"
    assert result.data["has_contributing"] is True
    assert result.data["has_code_of_conduct"] is False
    assert "installation" in result.data["readme_has_sections"]


def test_cicd_collector_detects_config_without_platform_api(local_source_repo, tmp_path):
    ctx = _make_ctx(local_source_repo, tmp_path)
    result = cicd.collect(ctx)

    assert result.data["has_ci_config"] is True
    assert result.data["ci_config_path"] == ".sourcecraft/ci.yaml"
    assert result.data["declared_stage_count"] == 3
    assert result.data["has_test_stage"] is True
    assert result.data["has_deploy_stage"] is True
    assert result.data["pipeline_history_available"] is False
    assert result.status == "partial"  # config known, run-history unavailable without a platform client


def test_code_health_collector_counts_markers(local_source_repo, tmp_path):
    ctx = _make_ctx(local_source_repo, tmp_path)
    result = code_health.collect(ctx)

    assert result.status == "ok"
    assert result.data["todo_count"] == 1
    assert result.data["fixme_count"] == 1
    assert result.data["hack_count"] == 0
    assert result.data["file_count"] == len(ctx.files)


def test_activity_collector_counts_commits(local_source_repo, tmp_path):
    ctx = _make_ctx(local_source_repo, tmp_path)
    result = activity.collect(ctx)

    assert result.data["commits_30d"] == 1
    assert result.data["contributors_365d"] == 1
    assert result.data["bus_factor_top1_share_365d"] == 1.0
    # No platform client -> PR/release/likes stay explicitly null, not missing keys.
    assert result.data["pull_requests"] == {
        "open": None, "merged_90d": None, "avg_merge_time_hours": None, "stale_open_count": None,
    }


def test_git_native_collectors_degrade_gracefully_on_an_empty_repo(empty_source_repo, tmp_path):
    """The real bug this locks in: HEAD doesn't resolve to a commit on a
    zero-commit repo, and `git clone` of one succeeds -- every collector
    must treat that as "nothing here" (empty results, no crash), not raise.
    """
    ctx = _make_ctx(empty_source_repo, tmp_path)

    assert ctx.git_repo.is_empty() is True
    assert ctx.files == []

    doc_result = documentation.collect(ctx)
    assert doc_result.data["has_readme"] is False

    code_health_result = code_health.collect(ctx)
    assert code_health_result.data["todo_count"] == 0
    assert code_health_result.data["file_count"] == 0

    activity_result = activity.collect(ctx)
    assert activity_result.data["commits_365d"] == 0
    assert activity_result.data["contributors_365d"] == 0
