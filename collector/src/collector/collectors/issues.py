"""Issues category: platform API only (repos/{owner}/{repo}/issues +
.../comments), both `verified: true` in config/endpoints.yaml -- confirmed
2026-09-19 against the live Redoc docs at api.sourcecraft.tech/docs/index.html.

Unlike GitHub, Issue objects here have no `number`/`state`/`closed_at`
fields: the per-repo identifier is `slug`, workflow state is a nested
`status{id,slug,name,status_type}` object (custom per repo/org, not a fixed
open/closed enum), and completion is tracked via `completed_at` (null while
open). We treat `completed_at != null` as "closed" rather than trying to
interpret `status_type`, since the full status_type enum isn't documented
and completed_at is an explicit, unambiguous field.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..errors import CollectorError
from ..time_utils import hours_between, parse_iso
from .base import CategoryResult, CollectorContext


def _first_response_hours(ctx: CollectorContext, issue: dict, created_at) -> float | None:
    slug = issue.get("slug")
    if slug is None or ctx.platform is None:
        return None
    try:
        comments = ctx.platform.paginate(
            "list_issue_comments",
            path_params={"owner": ctx.repo.owner, "repo": ctx.repo.name, "issue_slug": slug},
        )
    except CollectorError:
        return None
    if not comments:
        return None
    first = min(
        (parse_iso(c.get("created_at")) for c in comments if isinstance(c, dict)),
        default=None,
        key=lambda d: d or datetime.max.replace(tzinfo=timezone.utc),
    )
    return hours_between(created_at, first)


def collect(ctx: CollectorContext) -> CategoryResult:
    data: dict = {
        "open_count": None,
        "opened_90d": None,
        "closed_90d": None,
        "avg_time_to_first_response_hours": None,
        "avg_time_to_close_hours": None,
        "stale_open_count": None,
        "unanswered_open_count": None,
        "labels_in_use": None,
    }
    if ctx.platform is None:
        return CategoryResult(data=data, status="unavailable", errors=[])

    errors: list[dict] = []
    try:
        issues = ctx.platform.paginate("list_issues", path_params={"owner": ctx.repo.owner, "repo": ctx.repo.name})
    except CollectorError as exc:
        errors.append({"category": "issues", "source": exc.source, "code": exc.code, "message": exc.message})
        return CategoryResult(data=data, status="unavailable", errors=errors)

    issues = [i for i in issues if isinstance(i, dict)]

    now = datetime.now(timezone.utc)
    cutoff_90d = now.timestamp() - 90 * 86400

    open_issues = [i for i in issues if parse_iso(i.get("completed_at")) is None]
    opened_90d = [i for i in issues if (d := parse_iso(i.get("created_at"))) and d.timestamp() >= cutoff_90d]
    closed_90d = [i for i in issues if (d := parse_iso(i.get("completed_at"))) and d.timestamp() >= cutoff_90d]

    close_times = []
    for issue in closed_90d:
        created = parse_iso(issue.get("created_at"))
        completed = parse_iso(issue.get("completed_at"))
        hours = hours_between(created, completed)
        if hours is not None:
            close_times.append(hours)

    labels: set[str] = set()
    for issue in issues:
        for label in issue.get("labels") or []:
            name = label.get("name") if isinstance(label, dict) else label
            if isinstance(name, str):
                labels.add(name)

    stale_open = 0
    unanswered_open = 0
    response_times = []
    # First-response timing needs one comments-list call per issue; cap it so
    # a repo with thousands of open issues doesn't turn one collection run
    # into thousands of HTTP requests.
    for issue in open_issues[:50]:
        created_at = parse_iso(issue.get("created_at"))
        updated_at = parse_iso(issue.get("updated_at")) or created_at
        if updated_at and (now - updated_at).days > 30:
            stale_open += 1
        response_hours = _first_response_hours(ctx, issue, created_at)
        if response_hours is None:
            unanswered_open += 1
        else:
            response_times.append(response_hours)

    data.update(
        open_count=len(open_issues),
        opened_90d=len(opened_90d),
        closed_90d=len(closed_90d),
        avg_time_to_close_hours=(sum(close_times) / len(close_times)) if close_times else None,
        avg_time_to_first_response_hours=(sum(response_times) / len(response_times)) if response_times else None,
        stale_open_count=stale_open,
        unanswered_open_count=unanswered_open,
        labels_in_use=sorted(labels),
    )
    status = "partial" if errors else "ok"
    return CategoryResult(data=data, status=status, errors=errors)
