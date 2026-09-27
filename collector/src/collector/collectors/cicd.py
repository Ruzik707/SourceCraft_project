"""CI/CD category: config presence/shape is git-native (reads
.sourcecraft/ci.yaml, per sourcecraft.dev/portal/docs/ru/sourcecraft/operations/ci-cd).
Run-history (success rate, durations) uses the platform REST API's
"list_pipeline_runs" operation (repos/{owner}/{repo}/cicd/runs), confirmed
2026-09-19 against the live Redoc docs -- an earlier truncated crawl of the
raw swagger.json had wrongly concluded no such endpoint existed. Run objects
expose `status` and a nested `dates{created_at,started_at,finished_at,
updated_at}`; the full `status` enum beyond the single documented example
("created") isn't shown, so success/failure detection below is a best-effort
keyword match -- re-check against a real run's status string once available.
"""
from __future__ import annotations

import yaml

from ..errors import CollectorError
from ..time_utils import parse_iso
from .base import CategoryResult, CollectorContext

_CI_CONFIG_CANDIDATES = [".sourcecraft/ci.yaml", ".sourcecraft/ci.yml"]

_STAGE_KEYWORDS = {
    "test": ("test", "pytest", "unit"),
    "lint_or_security": ("lint", "security", "scan", "sast", "appsec"),
    "deploy": ("deploy", "release", "publish", "cd"),
}


def _detect_stage_kinds(raw_yaml_text: str) -> dict[str, bool]:
    lowered = raw_yaml_text.lower()
    return {kind: any(kw in lowered for kw in keywords) for kind, keywords in _STAGE_KEYWORDS.items()}


def _count_declared_stages(parsed: object) -> int | None:
    if not isinstance(parsed, dict):
        return None
    for key in ("stages", "jobs", "workflows", "cubes"):
        value = parsed.get(key)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return len(value)
    return None


def _collect_config(ctx: CollectorContext, data: dict) -> None:
    ci_path = next((f for f in ctx.files if f.lower() in _CI_CONFIG_CANDIDATES), None)
    data["has_ci_config"] = ci_path is not None
    data["ci_config_path"] = ci_path

    if not ci_path or ctx.git_repo is None:
        data.update(
            declared_stage_count=None,
            has_test_stage=None,
            has_lint_or_security_stage=None,
            has_deploy_stage=None,
        )
        return

    raw_text = ctx.git_repo.read_text(ci_path) or ""
    stage_kinds = _detect_stage_kinds(raw_text)
    data["has_test_stage"] = stage_kinds["test"]
    data["has_lint_or_security_stage"] = stage_kinds["lint_or_security"]
    data["has_deploy_stage"] = stage_kinds["deploy"]
    try:
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError:
        parsed = None
    data["declared_stage_count"] = _count_declared_stages(parsed)


def _collect_run_history(ctx: CollectorContext, data: dict, errors: list[dict]) -> None:
    data.update(
        pipeline_history_available=False,
        runs_30d=None,
        success_rate_30d=None,
        median_duration_seconds=None,
        last_run_status=None,
        last_run_at=None,
        branch_protection_enabled=None,  # no confirmed endpoint at all yet
    )
    if ctx.platform is None:
        return
    try:
        runs = ctx.platform.paginate(
            "list_pipeline_runs", path_params={"owner": ctx.repo.owner, "repo": ctx.repo.name}
        )
    except CollectorError as exc:
        errors.append({"category": "cicd", "source": exc.source, "code": exc.code, "message": exc.message})
        return

    data["pipeline_history_available"] = True
    recent = [r for r in runs[:30] if isinstance(r, dict)]
    data["runs_30d"] = len(recent)

    statuses = [r.get("status") for r in recent if r.get("status")]
    successes = [s for s in statuses if isinstance(s, str) and s.lower() in ("success", "succeeded", "finished", "passed", "completed")]
    data["success_rate_30d"] = (len(successes) / len(statuses)) if statuses else None

    durations = []
    for r in recent:
        dates = r.get("dates") or {}
        started = parse_iso(dates.get("started_at"))
        finished = parse_iso(dates.get("finished_at"))
        if started and finished:
            durations.append((finished - started).total_seconds())
    data["median_duration_seconds"] = sorted(durations)[len(durations) // 2] if durations else None

    if recent:
        latest = recent[0]
        latest_dates = latest.get("dates") or {}
        data["last_run_status"] = latest.get("status")
        data["last_run_at"] = latest_dates.get("created_at") or latest_dates.get("started_at")


def collect(ctx: CollectorContext) -> CategoryResult:
    data: dict = {}
    errors: list[dict] = []
    _collect_config(ctx, data)
    _collect_run_history(ctx, data, errors)

    status = "ok" if data.get("has_ci_config") and data.get("pipeline_history_available") else "partial"
    if ctx.git_repo is None:
        status = "unavailable"
    return CategoryResult(data=data, status=status, errors=errors)
