"""Client for the SourceCraft Security (AppSec) REST API -- SCS Backend API
1.0.0. Grounded in the organizer-provided draft spec (2026-09-16) plus the
base URL shared by organizers on 2026-09-19: https://appsec.sourcecraft.tech

Known gaps, called out explicitly rather than papered over:
- Auth scheme is NOT documented in the draft spec. We support a bearer
  token (APPSEC_TOKEN) and, as an alternative, a curl-style config file
  (APPSEC_CURL_CONFIG_PATH) since the organizer examples use
  `curl --config <file>`. Confirm the real scheme with #lct-hack support.
- The numeric forms of `status`/`severity` on some endpoints are explicitly
  undocumented in the spec ("не имеют таблицы соответствия") -- this client
  never touches those, only the string enum fields (e.g. severity=HIGH,
  status=RESOLVED_FP) that the spec does give literal examples for.
- Pagination end-of-list is not well-defined ("Признак окончания выдачи ...
  не определён"); see _paginate() for the conservative stopping rule used.
- Public repos get scan results without the Security Add-on connected
  (per organizer message, 2026-09-19); private/add-on-gated repos may 404 or
  403 -- both surface as `appsec_available: false` upstream, not a crash.
"""
from __future__ import annotations

import re
from pathlib import Path

import requests

from .endpoint_registry import EndpointRegistry
from .errors import UpstreamRequestError

_MAX_PAGES_SAFETY_CAP = 200


def _parse_curl_config_auth(path: str) -> dict[str, str]:
    """Minimal parser for the subset of curl --config syntax we care about:
    `header = "Authorization: Bearer xxx"` and `user = "name:pass"`.
    Returns extra requests-style kwargs to merge into the request.
    """
    extra_headers: dict[str, str] = {}
    text = Path(path).read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
        else:
            key, _, value = line.partition(" ")
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key == "header":
            header_name, _, header_value = value.partition(":")
            if header_name:
                extra_headers[header_name.strip()] = header_value.strip()
    return extra_headers


class AppSecClient:
    def __init__(
        self,
        registry: EndpointRegistry,
        *,
        token: str | None = None,
        curl_config_path: str | None = None,
        timeout_s: float = 30.0,
    ):
        self.registry = registry
        self.timeout_s = timeout_s
        self._extra_headers: dict[str, str] = {}
        if token:
            self._extra_headers["Authorization"] = f"Bearer {token}"
        elif curl_config_path:
            self._extra_headers.update(_parse_curl_config_auth(curl_config_path))
        self._session = requests.Session()

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", **self._extra_headers}

    def _get(self, operation_key: str, *, path_params: dict | None = None, query: dict | None = None) -> dict:
        op = self.registry.get(operation_key)
        path = op.resolve_path(**(path_params or {}))
        base_url = self.registry.default_base_url.rstrip("/")
        url = f"{base_url}/{path.lstrip('/')}"
        try:
            resp = self._session.get(url, headers=self._headers(), params=query, timeout=self.timeout_s)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            # Include the response body: a 403/404 status line alone doesn't
            # say whether the problem is a wrong gitRepo value, a token
            # that's valid but not entitled for AppSec, or a repo that
            # simply has no scan yet -- APIs usually explain which, in body.
            body = exc.response.text[:500] if exc.response is not None else ""
            raise UpstreamRequestError(
                f"GET {url} failed: {exc}" + (f" | body: {body}" if body else ""),
                source="appsec_api",
                code="HTTP_ERROR",
            ) from exc

    def _paginate(self, operation_key: str, *, git_repo: str, extra_query: dict | None = None, page_size: int = 50) -> list[dict]:
        """Cursor pagination per the draft spec: response has data /
        nextPageToken / totalSize, but no documented "last page" flag. We
        stop when nextPageToken is missing/empty, OR we've fetched
        >= totalSize (if given), OR after _MAX_PAGES_SAFETY_CAP pages,
        whichever comes first -- so a spec surprise can't hang the collector.
        """
        items: list[dict] = []
        page_token = ""
        total_size: int | None = None
        for _ in range(_MAX_PAGES_SAFETY_CAP):
            query = {"gitRepo": git_repo, "pageSize": page_size, "pageToken": page_token, **(extra_query or {})}
            payload = self._get(operation_key, query=query)
            batch = payload.get("data", [])
            items.extend(batch)
            total_size = payload.get("totalSize", total_size)
            page_token = payload.get("nextPageToken") or ""
            if not page_token:
                break
            if total_size is not None and len(items) >= total_size:
                break
            if not batch:
                break
        return items

    # --- scans -----------------------------------------------------------

    def latest_scan(self, git_repo: str) -> dict:
        # Deliberately does NOT swallow errors here: the draft spec doesn't
        # say how "no scan exists yet" is signaled (404? empty 200?) vs. a
        # real auth/permission failure, so hiding the exception behind a
        # bare `None` return made every failure mode look identical
        # upstream ("security": "not_applicable") -- including a wrong or
        # missing APPSEC_TOKEN, which is exactly what you can't debug that
        # way. Let callers (security.py) catch UpstreamRequestError and
        # surface the real HTTP status/message in collection.errors.
        return self._get("latest_scan", query={"gitRepo": git_repo})

    def list_scans(self, git_repo: str, *, status: str = "FINISHED", page_size: int = 50) -> list[dict]:
        return self._paginate("list_scans", git_repo=git_repo, extra_query={"status": status}, page_size=page_size)

    # --- defect groups -----------------------------------------------------

    def list_defect_groups(
        self,
        git_repo: str,
        *,
        scan_uuid: str | None = None,
        severity: list[str] | None = None,
        status: list[str] | None = None,
        page_size: int = 50,
    ) -> list[dict]:
        extra: dict = {}
        if scan_uuid:
            extra["scanUuid"] = scan_uuid
        if severity:
            extra["severity"] = severity
        if status:
            extra["status"] = status
        return self._paginate("list_defect_groups", git_repo=git_repo, extra_query=extra, page_size=page_size)

    def list_findings(self, git_repo: str, defect_group_uuid: str, *, page_size: int = 50) -> list[dict]:
        return self._paginate(
            "list_findings", git_repo=git_repo, extra_query={"defectGroupUuid": defect_group_uuid}, page_size=page_size
        )


_RESOLVED_STATUS_RE = re.compile(r"RESOLVED", re.IGNORECASE)


def summarize_defect_groups(defect_groups: list[dict]) -> dict:
    """Turn a raw list of DefectGroupDto-shaped dicts into the counts used in
    the `security` block of the output schema. Only reads `severity`,
    `status`, `type` and `createdAt`/`updatedAt`-ish fields defensively --
    unknown/missing keys just don't contribute to a bucket, they don't crash.
    """
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_engine_type: dict[str, int] = {}
    open_total = 0
    resolved_fp_total = 0

    for group in defect_groups:
        severity = group.get("severity")
        status = group.get("status")
        engine_type = group.get("type")

        if isinstance(severity, str):
            by_severity[severity] = by_severity.get(severity, 0) + 1
        if isinstance(status, str):
            by_status[status] = by_status.get(status, 0) + 1
            if not _RESOLVED_STATUS_RE.search(status):
                open_total += 1
            if status.upper() == "RESOLVED_FP":
                resolved_fp_total += 1
        if isinstance(engine_type, str):
            by_engine_type[engine_type] = by_engine_type.get(engine_type, 0) + 1

    return {
        "defect_groups_by_severity": by_severity,
        "defect_groups_by_status": by_status,
        "defect_groups_by_engine_type": by_engine_type,
        "open_defect_groups_total": open_total,
        "resolved_false_positive_total": resolved_fp_total,
    }
