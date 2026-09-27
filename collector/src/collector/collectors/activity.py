"""Activity category: commit/contributor/branch/tag stats are git-native.
Pull-request, release and "likes" stats need the platform API; endpoints
are confirmed (2026-09-19) against the live Redoc docs, but a few field
shapes differ from what you'd expect from GitHub -- see inline notes.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..errors import CollectorError
from ..time_utils import days_between, hours_between, median, parse_iso
from .base import CategoryResult, CollectorContext

_SEMVER_RE = re.compile(r"^v?\d+\.\d+\.\d+")


def _collect_git_activity(ctx: CollectorContext, data: dict) -> None:
    repo = ctx.git_repo
    if repo is None:
        data.update(
            commits_30d=None, commits_90d=None, commits_365d=None, last_commit_at=None,
            contributors_365d=None, bus_factor_top1_share_365d=None, branch_count=None, tag_count=None,
        )
        return

    commits_365d = repo.log(since="365 days ago")
    commits_90d = repo.log(since="90 days ago")
    commits_30d = repo.log(since="30 days ago")

    data["commits_30d"] = len(commits_30d)
    data["commits_90d"] = len(commits_90d)
    data["commits_365d"] = len(commits_365d)
    last_commit = repo.last_commit_at()
    data["last_commit_at"] = last_commit.isoformat() if last_commit else None

    author_counts: dict[str, int] = {}
    for commit in commits_365d:
        author_counts[commit.author_email] = author_counts.get(commit.author_email, 0) + 1
    data["contributors_365d"] = len(author_counts)
    data["bus_factor_top1_share_365d"] = (
        max(author_counts.values()) / len(commits_365d) if commits_365d and author_counts else None
    )

    data["branch_count"] = repo.remote_branch_count(ctx.repo.clone_url)
    data["tag_count"] = repo.remote_tag_count(ctx.repo.clone_url)


_PR_OPEN_LIKE_STATUSES = {"open", "draft", "merging"}


def _collect_pull_requests(ctx: CollectorContext, data: dict, errors: list[dict]) -> None:
    data["pull_requests"] = {"open": None, "merged_90d": None, "avg_merge_time_hours": None, "stale_open_count": None}
    if ctx.platform is None:
        return
    try:
        prs = ctx.platform.paginate("list_pull_requests", path_params={"owner": ctx.repo.owner, "repo": ctx.repo.name})
    except CollectorError as exc:
        errors.append({"category": "activity", "source": exc.source, "code": exc.code, "message": exc.message})
        return

    # PR objects have a flat `status` string -- one of draft/open/discarded/
    # merging/merged (confirmed via live docs) -- not GitHub's `state`, and
    # there is NO `merged_at` timestamp. "Merge time" below is approximated
    # from `updated_at` on status=="merged" PRs, which is only exact if
    # nothing else touched the PR after it merged.
    now = datetime.now(timezone.utc)
    cutoff_90d = now.timestamp() - 90 * 86400
    open_prs = [pr for pr in prs if isinstance(pr, dict) and (pr.get("status") or "").lower() in _PR_OPEN_LIKE_STATUSES]
    merged_prs_90d = []
    merge_times_hours: list[float] = []
    stale_open = 0
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        status = (pr.get("status") or "").lower()
        created_at = parse_iso(pr.get("created_at"))
        updated_at = parse_iso(pr.get("updated_at"))
        if status == "merged" and updated_at and updated_at.timestamp() >= cutoff_90d:
            merged_prs_90d.append(pr)
            hours = hours_between(created_at, updated_at)
            if hours is not None:
                merge_times_hours.append(hours)
        if status in _PR_OPEN_LIKE_STATUSES:
            reference = updated_at or created_at
            if reference and days_between(reference, now) and days_between(reference, now) > 30:
                stale_open += 1

    data["pull_requests"] = {
        "open": len(open_prs),
        "merged_90d": len(merged_prs_90d),
        "avg_merge_time_hours": (sum(merge_times_hours) / len(merge_times_hours)) if merge_times_hours else None,
        "stale_open_count": stale_open,
    }


def _collect_releases(ctx: CollectorContext, data: dict, errors: list[dict]) -> None:
    data["releases"] = {"count": None, "last_release_at": None, "median_interval_days": None, "uses_semver": None}
    if ctx.platform is None:
        return
    try:
        releases = ctx.platform.paginate("list_releases", path_params={"owner": ctx.repo.owner, "repo": ctx.repo.name})
    except CollectorError as exc:
        errors.append({"category": "activity", "source": exc.source, "code": exc.code, "message": exc.message})
        return

    # Confirmed field names are `tag` and `released_at` (not GitHub's
    # `tag_name`/`published_at`).
    dates = sorted(
        (d for d in (parse_iso(r.get("released_at") or r.get("created_at")) for r in releases if isinstance(r, dict)) if d)
    )
    intervals = [days_between(dates[i], dates[i + 1]) for i in range(len(dates) - 1)]
    tags = [r.get("tag") for r in releases if isinstance(r, dict) and r.get("tag")]
    data["releases"] = {
        "count": len(releases),
        "last_release_at": dates[-1].isoformat() if dates else None,
        "median_interval_days": median([i for i in intervals if i is not None]),
        "uses_semver": (all(_SEMVER_RE.match(t) for t in tags) if tags else None),
    }


def _collect_likes(ctx: CollectorContext, data: dict, errors: list[dict]) -> None:
    data["likes"] = {"value": None, "percentile": None, "source": None}
    if ctx.platform is None:
        return
    # Aggregate rating/likes lives on the repo object itself
    # (get_repo -> rating{value,percentile,reaction_counts}), NOT on the
    # `.../rating` sub-resource, which turned out to be the current
    # authenticated user's own reaction, not an aggregate -- see
    # config/endpoints.yaml (get_repository_rating).
    try:
        repo = ctx.platform.call("get_repo", path_params={"owner": ctx.repo.owner, "repo": ctx.repo.name})
    except CollectorError as exc:
        errors.append({"category": "activity", "source": exc.source, "code": exc.code, "message": exc.message})
        return
    rating = repo.get("rating") if isinstance(repo, dict) else None
    if isinstance(rating, dict):
        data["likes"] = {
            "value": rating.get("value"),
            "percentile": rating.get("percentile"),
            "source": "platform_api:get_repo.rating",
        }


def collect(ctx: CollectorContext) -> CategoryResult:
    data: dict = {}
    errors: list[dict] = []
    _collect_git_activity(ctx, data)
    _collect_pull_requests(ctx, data, errors)
    _collect_releases(ctx, data, errors)
    _collect_likes(ctx, data, errors)

    if ctx.git_repo is None:
        status = "unavailable"
    elif errors:
        status = "partial"
    else:
        status = "ok"
    return CategoryResult(data=data, status=status, errors=errors)
