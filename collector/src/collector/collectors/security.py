"""Security category: sourced from the SourceCraft Security (AppSec) API --
see appsec_client.py for the full grounding. We deliberately do NOT run our
own scanner here (out of scope per the case brief: "security-данные берём из
AppSec SourceCraft, свой сканер не пишем").
"""
from __future__ import annotations

from ..appsec_client import summarize_defect_groups
from ..errors import CollectorError
from .base import CategoryResult, CollectorContext


def _has_security_policy(ctx: CollectorContext) -> bool | None:
    if not ctx.files:
        return None
    return any(f.lower() in ("security.md", ".sourcecraft/security.md", ".github/security.md") for f in ctx.files)


def collect(ctx: CollectorContext) -> CategoryResult:
    data: dict = {
        "appsec_available": False,
        "latest_scan": None,
        "defect_groups_by_severity": None,
        "defect_groups_by_status": None,
        "defect_groups_by_engine_type": None,
        "open_defect_groups_total": None,
        "resolved_false_positive_total": None,
        "oldest_open_defect_group_age_days": None,
        "has_security_policy": _has_security_policy(ctx),
    }

    if ctx.appsec is None or ctx.repo.gitrepo_id is None:
        return CategoryResult(data=data, status="not_applicable", errors=[])

    errors: list[dict] = []
    try:
        latest = ctx.appsec.latest_scan(ctx.repo.gitrepo_id)
        if latest:
            data["appsec_available"] = True
            data["latest_scan"] = {
                "scan_uuid": latest.get("uuid"),
                "status": latest.get("status"),
                "scan_type": latest.get("scanType") or latest.get("type"),
                "finished_at": latest.get("finishedAt") or latest.get("finished_at"),
            }
            scan_uuid = latest.get("uuid")
            defect_groups = ctx.appsec.list_defect_groups(ctx.repo.gitrepo_id, scan_uuid=scan_uuid)
            data.update(summarize_defect_groups(defect_groups))
    except CollectorError as exc:
        errors.append({"category": "security", "source": exc.source, "code": exc.code, "message": exc.message})

    if not data["appsec_available"]:
        status = "unavailable" if errors else "not_applicable"
    elif errors:
        status = "partial"
    else:
        status = "ok"
    return CategoryResult(data=data, status=status, errors=errors)
