"""Shared contract for the six category collectors.

Each collector is a plain function `collect(ctx: CollectorContext) -> CategoryResult`.
`run_category()` wraps it so one category blowing up (network error, git
failure, unexpected API shape) can't take down the other five -- it always
returns a CategoryResult, downgrading to status="unavailable" and recording
the error instead of raising.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

from ..appsec_client import AppSecClient
from ..errors import CollectorError
from ..git_client import GitRepo
from ..platform_client import PlatformClient
from ..repo_ref import RepoRef

CategoryStatus = Literal["ok", "partial", "unavailable", "not_applicable"]


@dataclass
class CollectorContext:
    repo: RepoRef
    git_repo: Optional[GitRepo]
    platform: Optional[PlatformClient]
    appsec: Optional[AppSecClient]
    files: list[str] = field(default_factory=list)  # cached `git ls-tree` output


@dataclass
class CategoryResult:
    data: dict
    status: CategoryStatus
    errors: list[dict] = field(default_factory=list)


def run_category(name: str, fn: Callable[[CollectorContext], CategoryResult], ctx: CollectorContext) -> CategoryResult:
    try:
        return fn(ctx)
    except CollectorError as exc:
        return CategoryResult(
            data={},
            status="unavailable",
            errors=[{"category": name, "source": exc.source, "code": exc.code, "message": exc.message}],
        )
    except Exception as exc:  # noqa: BLE001 - last-resort guard, see module docstring
        return CategoryResult(
            data={},
            status="unavailable",
            errors=[{"category": name, "source": None, "code": "UNEXPECTED_ERROR", "message": str(exc)}],
        )
