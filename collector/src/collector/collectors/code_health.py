"""Code health category: git-native static counting only (TODO/FIXME/HACK
markers, line counts). No linting, no execution -- static analysis findings
belong to the security/AppSec category per the case brief, not here.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..git_client import has_todo_marker, is_countable_source_file, scan_todos
from .base import CategoryResult, CollectorContext

_MAX_FILES_FOR_BLAME_PROXY = 500


def _oldest_todo_age_days(ctx: CollectorContext, todo_files: list[str]) -> float | None:
    """Proxy, not a true `git blame` line-age: uses each TODO-containing
    file's last-touched date and reports the oldest of those. Cheap (one
    `git log` per file) and monotonic with the real answer in the common
    case where TODO-bearing lines aren't touched much after being added --
    but it will UNDER-estimate age for a file whose unrelated lines were
    edited more recently than the TODO itself. Good enough for a health
    signal, not for auditing a specific TODO.
    """
    if ctx.git_repo is None or not todo_files:
        return None
    if len(todo_files) > _MAX_FILES_FOR_BLAME_PROXY:
        todo_files = todo_files[:_MAX_FILES_FOR_BLAME_PROXY]

    now = datetime.now(timezone.utc)
    oldest_days: float | None = None
    for relpath in todo_files:
        changed_at = ctx.git_repo.file_last_change_at(relpath)
        if changed_at is None:
            continue
        age = (now - changed_at).total_seconds() / 86400.0
        if oldest_days is None or age > oldest_days:
            oldest_days = age
    return oldest_days


def collect(ctx: CollectorContext) -> CategoryResult:
    if ctx.git_repo is None:
        return CategoryResult(data={}, status="unavailable", errors=[
            {"category": "code_health", "source": "git", "code": "NO_CLONE", "message": "repository was not cloned"}
        ])

    files = ctx.files
    countable_files = [f for f in files if is_countable_source_file(f)]

    todo_counts = scan_todos(ctx.git_repo, countable_files)
    todo_bearing_files = [
        f for f in countable_files if (text := ctx.git_repo.read_text(f)) and has_todo_marker(text)
    ]

    line_counts = [ctx.git_repo.file_line_count(f) or 0 for f in countable_files]
    total_lines = sum(line_counts)
    kloc = total_lines / 1000.0
    total_markers = sum(todo_counts.values())

    data = {
        "file_count": len(files),
        "lines_of_code_estimate": total_lines,
        "todo_count": todo_counts["TODO"],
        "fixme_count": todo_counts["FIXME"],
        "hack_count": todo_counts["HACK"],
        "todo_density_per_kloc": (total_markers / kloc) if kloc > 0 else None,
        "oldest_todo_age_days": _oldest_todo_age_days(ctx, todo_bearing_files),
        "largest_file_lines": max(line_counts) if line_counts else None,
    }
    return CategoryResult(data=data, status="ok", errors=[])
