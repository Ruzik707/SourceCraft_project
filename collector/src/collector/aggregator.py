"""Runs all six category collectors for one repository and assembles the
final record matching schema/repo_health.schema.json. This is the one place
that knows the full output shape -- category collectors only know their own
block.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .appsec_client import AppSecClient
from .collectors import activity, cicd, code_health, documentation, issues, security
from .collectors.base import CategoryResult, CollectorContext, run_category
from .config import Settings
from .endpoint_registry import EndpointRegistry, load_registry
from .errors import CollectorError
from .git_client import GitRepo
from .platform_client import PlatformClient
from .repo_ref import RepoRef

_CATEGORY_COLLECTORS = {
    "documentation": documentation.collect,
    "cicd": cicd.collect,
    "security": security.collect,
    "activity": activity.collect,
    "issues": issues.collect,
    "code_health": code_health.collect,
}


def _collect_repo_metadata(repo_ref: RepoRef, git_repo: GitRepo | None, platform: PlatformClient) -> dict:
    metadata = {
        "platform_id": repo_ref.gitrepo_id,
        "owner": repo_ref.owner,
        "name": repo_ref.name,
        "full_path": repo_ref.full_path,
        "url": None,
        "clone_url": repo_ref.clone_url,
        "description": None,
        "visibility": None,
        "default_branch": git_repo.current_branch() if git_repo else None,
        "primary_language": None,
        "languages": None,
        "topics": [],
        "created_at": None,
    }
    try:
        # Confirmed shape (2026-09-19, live Redoc docs): `web_url` not
        # `html_url`, `language` is an object ({name, color}) not a bare
        # string, and there is no `topics`/`created_at` field on the repo
        # object at all -- both stay at their defaults below.
        remote = platform.call("get_repo", path_params={"owner": repo_ref.owner, "repo": repo_ref.name})
    except CollectorError:
        return metadata
    if isinstance(remote, dict):
        metadata["url"] = remote.get("web_url") or metadata["url"]
        metadata["description"] = remote.get("description")
        metadata["visibility"] = remote.get("visibility")
        metadata["default_branch"] = remote.get("default_branch") or metadata["default_branch"]
        metadata["primary_language"] = (remote.get("language") or {}).get("name")
        metadata["topics"] = remote.get("topics") or []
        metadata["created_at"] = remote.get("created_at")
    return metadata


def collect_repo(
    repo_ref: RepoRef,
    settings: Settings,
    registries: dict[str, EndpointRegistry] | None = None,
    *,
    keep_workdir: bool = False,
    platform: PlatformClient | None = None,
    appsec: AppSecClient | None = None,
) -> dict:
    """`platform`/`appsec` are normally left None (real clients are built from
    `settings`); tests inject fakes here instead of hitting the real
    SourceCraft services.
    """
    started = time.monotonic()
    registries = registries or load_registry()

    platform = platform or PlatformClient(
        registries["platform_api"], token=settings.sourcecraft_token, cli_path=settings.sourcecraft_cli_path
    )
    appsec = appsec or AppSecClient(
        registries["appsec_api"], token=settings.appsec_token, curl_config_path=settings.appsec_curl_config_path
    )

    git_repo: GitRepo | None = None
    git_error: dict | None = None
    dest_dir = Path(settings.workdir) / repo_ref.workdir_name
    try:
        git_repo = GitRepo.clone(repo_ref.clone_url, dest_dir, shallow_since=settings.git_shallow_since)
    except CollectorError as exc:
        git_error = {"category": "collection", "source": exc.source, "code": exc.code, "message": exc.message}

    files = git_repo.list_files() if git_repo else []
    ctx = CollectorContext(repo=repo_ref, git_repo=git_repo, platform=platform, appsec=appsec, files=files)

    try:
        repo_metadata = _collect_repo_metadata(repo_ref, git_repo, platform)

        results: dict[str, CategoryResult] = {
            name: run_category(name, fn, ctx) for name, fn in _CATEGORY_COLLECTORS.items()
        }

        all_errors = list(git_error and [git_error] or [])
        for result in results.values():
            all_errors.extend(result.errors)

        record = {
            "schema_version": "1.0.0",
            "repo": repo_metadata,
            "collection": {
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "collector_version": __version__,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "sources_used": {
                    "git_clone": git_repo is not None,
                    "platform_api": settings.sourcecraft_token is not None,
                    "platform_cli": False,
                    "appsec_api": bool(settings.appsec_token or settings.appsec_curl_config_path),
                },
                "category_status": {name: result.status for name, result in results.items()},
                "errors": all_errors,
            },
            **{name: result.data for name, result in results.items()},
        }
        return record
    finally:
        if git_repo and not keep_workdir:
            git_repo.cleanup()
