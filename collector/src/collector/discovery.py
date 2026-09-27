"""Finds which repositories to run the collector against, per the case
brief's "open repositories of SourceCraft" resource -- confirmed sufficient
by the task moderator (no separate organizer-provided list is required).

Uses the platform API's global `list_repos` (GET /repos) or org-scoped
`list_org_repos` (GET /orgs/{org_slug}/repos), both confirmed 2026-09-19
against the live Redoc docs, and filters client-side on
`visibility == "public"` since it's unconfirmed whether the API itself
accepts a visibility query filter.
"""
from __future__ import annotations

from .errors import CollectorError
from .platform_client import PlatformClient
from .repo_ref import RepoRef


def discover_open_repos(platform: PlatformClient, *, org_slug: str | None = None) -> list[RepoRef]:
    if org_slug:
        repos = platform.paginate("list_org_repos", path_params={"org_slug": org_slug})
    else:
        repos = platform.paginate("list_repos")

    refs: list[RepoRef] = []
    for repo in repos:
        if not isinstance(repo, dict) or repo.get("visibility") != "public":
            continue
        org = repo.get("organization") or {}
        clone_urls = repo.get("clone_url") or {}
        # Prefer SSH: the https clone_url has been observed to route through
        # sourcecraft.dev's browser OAuth flow (captcha included) for at
        # least some hosts, which a non-interactive collector run can't
        # complete -- see docs/data-collector.md. SSH just needs a key.
        clone_url = clone_urls.get("ssh") or clone_urls.get("https")
        if not clone_url or not org.get("slug") or not repo.get("slug"):
            continue
        refs.append(
            RepoRef(
                owner=org["slug"],
                name=repo["slug"],
                clone_url=clone_url,
                # `id` as the AppSec `gitRepo` value is an unverified guess
                # (see config/endpoints.yaml get_repo) -- test empirically.
                gitrepo_id=repo.get("id"),
            )
        )
    return refs
