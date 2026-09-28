"""End-to-end wiring test: runs the real aggregator against a local git repo
(no network for the git-native categories) with fake platform/AppSec clients
standing in for the real HTTP calls, so this suite never touches the actual
SourceCraft services. Checks both the individual field wiring and that the
whole record still matches the published JSON Schema.
"""
from __future__ import annotations

from pathlib import Path

from collector.aggregator import collect_repo
from collector.config import Settings
from collector.endpoint_registry import load_registry
from collector.repo_ref import RepoRef
from collector.schema_validate import validate_record


class FakePlatformClient:
    """Fake data below mirrors the CONFIRMED real API shapes (2026-09-19,
    live Redoc docs at api.sourcecraft.tech/docs/index.html) -- not GitHub's
    shapes. Issues use `slug`/`status`/`completed_at`, not `number`/`state`/
    `closed_at`; PRs use a flat `status` string with no `merged_at`;
    releases use `tag`/`released_at`; rating is embedded on get_repo.
    """

    def __init__(self):
        self.calls: dict[str, object] = {
            "get_repo": {
                "description": "A demo repo",
                "visibility": "public",
                "default_branch": "main",
                "language": {"name": "Python", "color": "#3572A5"},
                "web_url": "https://sourcecraft.dev/acme/demo",
                "rating": {"value": 0.82, "percentile": 0.91, "reaction_counts": []},
            },
        }
        self.paginated: dict[str, list] = {
            "list_issue_comments": [{"created_at": "2026-09-10T12:00:00Z"}],
            "list_issues": [
                {"slug": "ISSUE-1", "status": {"slug": "open", "name": "Open", "status_type": "initial"},
                 "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-10T00:00:00Z",
                 "completed_at": None, "labels": [{"name": "bug"}]},
                {"slug": "ISSUE-2", "status": {"slug": "done", "name": "Done", "status_type": "final"},
                 "created_at": "2026-08-01T00:00:00Z", "updated_at": "2026-08-05T00:00:00Z",
                 "completed_at": "2026-08-05T00:00:00Z", "labels": []},
            ],
            "list_pull_requests": [
                {"status": "open", "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-15T00:00:00Z"},
                {"status": "merged", "created_at": "2026-08-01T00:00:00Z", "updated_at": "2026-08-02T00:00:00Z"},
            ],
            "list_releases": [
                {"tag": "v1.0.0", "released_at": "2026-07-01T00:00:00Z"},
                {"tag": "v1.1.0", "released_at": "2026-08-01T00:00:00Z"},
            ],
            "list_pipeline_runs": [
                {"status": "success",
                 "dates": {"created_at": "2026-09-18T00:00:00Z", "started_at": "2026-09-18T00:00:00Z", "finished_at": "2026-09-18T00:02:00Z"}},
                {"status": "failed",
                 "dates": {"created_at": "2026-09-17T00:00:00Z", "started_at": "2026-09-17T00:00:00Z", "finished_at": "2026-09-17T00:01:30Z"}},
            ],
        }

    def call(self, operation_key, *, path_params=None, query=None):
        return self.calls[operation_key]

    def paginate(self, operation_key, *, path_params=None, query=None, max_pages=200):
        return self.paginated[operation_key]


class FakeAppSecClient:
    def latest_scan(self, git_repo):
        return {"uuid": "scan-1", "status": "FINISHED", "scanType": "SCAN_TYPE_DEFAULT", "finishedAt": "2026-09-17T03:00:00Z"}

    def list_defect_groups(self, git_repo, *, scan_uuid=None, severity=None, status=None, page_size=50):
        return [
            {"severity": "HIGH", "status": "OPEN", "type": "SAST"},
            {"severity": "CRITICAL", "status": "RESOLVED_FP", "type": "SCA"},
        ]


def test_collect_repo_end_to_end(local_source_repo: Path, tmp_path: Path):
    settings = Settings(
        sourcecraft_token=None,
        appsec_token=None,
        appsec_curl_config_path=None,
        workdir=tmp_path / "workdir",
        output_dir=tmp_path / "output",
        git_shallow_since="30 days ago",
    )
    repo_ref = RepoRef(owner="acme", name="demo", clone_url=str(local_source_repo), gitrepo_id="fake-gitrepo-uuid")

    record = collect_repo(
        repo_ref, settings, load_registry(), platform=FakePlatformClient(), appsec=FakeAppSecClient()
    )

    assert validate_record(record) == []

    assert record["repo"]["description"] == "A demo repo"
    assert record["issues"]["open_count"] == 1
    assert record["issues"]["closed_90d"] == 1
    assert record["activity"]["pull_requests"]["open"] == 1
    assert record["activity"]["pull_requests"]["merged_90d"] == 1
    assert record["activity"]["releases"]["count"] == 2
    assert record["activity"]["releases"]["uses_semver"] is True
    assert record["activity"]["likes"]["value"] == 0.82
    assert record["activity"]["likes"]["percentile"] == 0.91
    assert record["cicd"]["pipeline_history_available"] is True
    assert record["cicd"]["runs_30d"] == 2
    assert record["cicd"]["success_rate_30d"] == 0.5
    assert record["security"]["appsec_available"] is True
    assert record["security"]["open_defect_groups_total"] == 1
    assert record["security"]["resolved_false_positive_total"] == 1
    assert record["collection"]["category_status"]["documentation"] == "ok"


def test_collect_repo_does_not_crash_on_an_empty_repo(empty_source_repo: Path, tmp_path: Path):
    """Regression test for a real crash found live: cloning a genuinely
    empty repo (zero commits) succeeded, but the very next step -- listing
    files off HEAD -- blew up before any per-category error handling could
    catch it, taking down the whole repo's collection instead of just
    reporting empty git-native categories.
    """
    settings = Settings(
        sourcecraft_token=None,
        appsec_token=None,
        appsec_curl_config_path=None,
        workdir=tmp_path / "workdir",
        output_dir=tmp_path / "output",
        git_shallow_since="30 days ago",
    )
    repo_ref = RepoRef(owner="acme", name="empty", clone_url=str(empty_source_repo), gitrepo_id=None)

    record = collect_repo(
        repo_ref, settings, load_registry(), platform=FakePlatformClient(), appsec=FakeAppSecClient()
    )

    assert validate_record(record) == []
    assert record["documentation"]["has_readme"] is False
    assert record["code_health"]["file_count"] == 0
    assert record["activity"]["commits_365d"] == 0
    # "partial", not "unavailable"/a crash: git-native categories run fine on
    # an empty repo, they just honestly have nothing to report (no README,
    # e.g., is a real partial-data signal, not a collection failure).
    assert record["collection"]["category_status"]["documentation"] == "partial"
    assert record["collection"]["category_status"]["code_health"] == "ok"
