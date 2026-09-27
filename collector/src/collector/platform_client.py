"""Client for the SourceCraft platform REST API (issues, pull requests,
releases, pipelines, rating). Paths come from the endpoint registry, never
hardcoded here -- see config/endpoints.yaml for what's confirmed vs. guessed.

Falls back to the `src api` CLI (mirrors `gh api`: `src api repos/{owner}/{repo}/issues`)
when direct REST calls can't be made, e.g. in a dev environment where only the
CLI is authenticated. Set `use_cli_fallback=False` to disable.
"""
from __future__ import annotations

import json
import subprocess
import time
import warnings

import requests

from .endpoint_registry import EndpointRegistry, Operation
from .errors import EndpointUnverifiedError, UpstreamRequestError

# Found live running a 1000-repo batch: a single transient read timeout on
# GET /repos (nothing wrong with the request itself) took down the whole
# run before it even started collecting. Retrying a couple of times with a
# short backoff is standard practice for a client meant to run unattended
# for a while -- only for genuinely transient failures (timeout/connection
# reset), never for a real HTTP error status (403/404/etc -- retrying those
# would just be spamming a request the server has already told us no to).
_TRANSIENT_RETRIES = 3
_TRANSIENT_BACKOFF_S = 2.0

# 429 is its own case, also found live: near the tail of the same 1000-repo
# batch (at concurrency=24, sustained over a couple of hours with a brief
# spike to 48), the platform API started answering
# {"error_code":"..."} 429 Too Many Requests on every category at once.
# Unlike a real 403/404, this is the server asking us to slow down, not
# telling us no -- worth retrying, with a longer backoff than a plain
# network blip, and honoring `Retry-After` if the server sends one.
_RATE_LIMIT_RETRIES = 4
_RATE_LIMIT_BACKOFF_S = 5.0


class PlatformClient:
    def __init__(
        self,
        registry: EndpointRegistry,
        *,
        token: str | None,
        cli_path: str = "src",
        use_cli_fallback: bool = True,
        require_verified: bool = False,
        timeout_s: float = 30.0,
    ):
        self.registry = registry
        self.token = token
        self.cli_path = cli_path
        self.use_cli_fallback = use_cli_fallback
        self.require_verified = require_verified
        self.timeout_s = timeout_s
        self._session = requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _check_verified(self, op: Operation) -> None:
        if self.require_verified and not op.verified:
            raise EndpointUnverifiedError(
                f"operation '{op.key}' is not verified against the live API "
                f"(config/endpoints.yaml: verified=false). Source note: {op.source}",
                source="platform_api",
                code="ENDPOINT_UNCONFIRMED",
            )

    def call(self, operation_key: str, *, path_params: dict | None = None, query: dict | None = None) -> dict | list:
        op = self.registry.get(operation_key)
        self._check_verified(op)
        path = op.resolve_path(**(path_params or {}))
        base_url = self.registry.default_base_url.rstrip("/")
        url = f"{base_url}/{path.lstrip('/')}"

        exc: requests.RequestException
        rate_limit_attempts = 0
        transient_attempts = 0
        while True:
            try:
                resp = self._session.request(op.method, url, headers=self._headers(), params=query, timeout=self.timeout_s)
                if resp.status_code == 429:
                    if rate_limit_attempts >= _RATE_LIMIT_RETRIES:
                        exc = requests.HTTPError(f"429 rate limited after {rate_limit_attempts} retries", response=resp)
                        break
                    retry_after = resp.headers.get("Retry-After", "")
                    delay = float(retry_after) if retry_after.isdigit() else _RATE_LIMIT_BACKOFF_S * (rate_limit_attempts + 1)
                    rate_limit_attempts += 1
                    time.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (requests.Timeout, requests.ConnectionError) as transient_exc:
                exc = transient_exc
                transient_attempts += 1
                if transient_attempts < _TRANSIENT_RETRIES:
                    time.sleep(_TRANSIENT_BACKOFF_S * transient_attempts)
                    continue
                break
            except requests.RequestException as real_exc:
                exc = real_exc  # real HTTP error status (403/404/...) -- no point retrying
                break

        body = exc.response.text[:500] if exc.response is not None else ""
        http_error_msg = f"{op.method} {url} failed: {exc}" + (f" | body: {body}" if body else "")
        if not self.use_cli_fallback:
            raise UpstreamRequestError(http_error_msg, source="platform_api", code="HTTP_ERROR") from exc
        try:
            return self._call_via_cli(path, query)
        except UpstreamRequestError as cli_exc:
            raise UpstreamRequestError(
                f"{http_error_msg} (CLI fallback also failed: {cli_exc.message})",
                source="platform_api",
                code="HTTP_ERROR",
            ) from exc

    def _call_via_cli(self, path: str, query: dict | None) -> dict | list:
        args = [self.cli_path, "api", path]
        for key, value in (query or {}).items():
            args += ["-f", f"{key}={value}"]
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
        except FileNotFoundError as exc:
            raise UpstreamRequestError(
                f"REST call failed and `{self.cli_path}` CLI is not on PATH", source="platform_cli", code="CLI_NOT_FOUND"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise UpstreamRequestError(f"`{self.cli_path} api {path}` timed out", source="platform_cli", code="TIMEOUT") from exc

        if proc.returncode != 0:
            raise UpstreamRequestError(
                f"`{self.cli_path} api {path}` failed: {proc.stderr.strip()}",
                source="platform_cli",
                code="CLI_NONZERO_EXIT",
            )
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise UpstreamRequestError(
                f"`{self.cli_path} api {path}` did not return JSON", source="platform_cli", code="BAD_JSON"
            ) from exc

    def paginate(self, operation_key: str, *, path_params: dict | None = None, query: dict | None = None, max_pages: int = 2000) -> list:
        """Cursor pagination confirmed against the live Redoc docs
        (2026-09-19): every list response has the shape
        `{"<list_key>": [...], "next_page_token": "string"}` -- there is no
        page/per_page style on this API. We stop on the first of: an empty
        `next_page_token`, an empty batch, or `max_pages` reached (the docs
        don't say what an empty vs. missing token means at the true end of a
        list, so the cap is a safety net, mirroring appsec_client's approach).

        `max_pages` defaults high (200,000 items at page_size=100) because a
        global listing turned out to have ~20,000 entries in practice --
        confirmed live against `list_repos` on 2026-09-19, where the default
        of 200 pages (20,000 items) silently looked like it might have been
        the true list length instead of our own cap. If this loop exhausts
        `max_pages` without the list naturally ending, it now warns instead
        of returning a truncated list that looks complete.
        """
        op = self.registry.get(operation_key)
        if op.pagination != "cursor":
            result = self.call(operation_key, path_params=path_params, query=query)
            if isinstance(result, list):
                return result
            if op.list_key and isinstance(result, dict):
                return result.get(op.list_key, [])
            return [result]

        items: list = []
        page_token = ""
        for _ in range(max_pages):
            page_query = {**(query or {}), "page_size": 100, "page_token": page_token}
            payload = self.call(operation_key, path_params=path_params, query=page_query)
            if not isinstance(payload, dict):
                break
            batch = payload.get(op.list_key, []) if op.list_key else []
            items.extend(batch)
            page_token = payload.get("next_page_token") or ""
            if not page_token or not batch:
                break
        else:
            warnings.warn(
                f"paginate('{operation_key}') hit max_pages={max_pages} without the list ending "
                f"(next_page_token was still non-empty) -- result of {len(items)} items is likely "
                f"TRUNCATED, not complete. Raise max_pages if this operation can legitimately have more.",
                stacklevel=2,
            )
        return items
