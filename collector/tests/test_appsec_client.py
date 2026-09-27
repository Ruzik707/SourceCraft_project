"""Pagination in the AppSec client has to be conservative: the draft spec
(see docs/appsec-api-notes.md) doesn't define an end-of-list flag, so we stop
on nextPageToken being empty OR len(items) >= totalSize OR a page count
safety cap -- whichever comes first. These tests drive `_get` directly
(monkeypatched) rather than hitting the network.
"""
from __future__ import annotations

from collector.appsec_client import AppSecClient, summarize_defect_groups
from collector.endpoint_registry import load_registry


def _client() -> AppSecClient:
    registries = load_registry()
    return AppSecClient(registries["appsec_api"], token="fake-token-for-tests")


def test_paginate_stops_on_empty_next_page_token(monkeypatch):
    client = _client()
    pages = [
        {"data": [{"id": 1}, {"id": 2}], "nextPageToken": "abc", "totalSize": 3},
        {"data": [{"id": 3}], "nextPageToken": "", "totalSize": 3},
    ]

    def fake_get(operation_key, *, path_params=None, query=None):
        return pages.pop(0)

    monkeypatch.setattr(client, "_get", fake_get)
    items = client._paginate("list_defect_groups", git_repo="repo-uuid")

    assert [item["id"] for item in items] == [1, 2, 3]


def test_paginate_stops_when_total_size_reached_even_with_token_present(monkeypatch):
    client = _client()
    calls = {"count": 0}

    def fake_get(operation_key, *, path_params=None, query=None):
        calls["count"] += 1
        # Server keeps sending a (buggy) non-empty nextPageToken even though
        # totalSize was already reached -- our loop must not trust that alone.
        return {"data": [{"id": 1}], "nextPageToken": "still-more", "totalSize": 1}

    monkeypatch.setattr(client, "_get", fake_get)
    items = client._paginate("list_defect_groups", git_repo="repo-uuid")

    assert len(items) == 1
    assert calls["count"] == 1


def test_summarize_defect_groups_counts_by_severity_status_and_engine():
    groups = [
        {"severity": "HIGH", "status": "OPEN", "type": "SAST"},
        {"severity": "HIGH", "status": "OPEN", "type": "SAST"},
        {"severity": "CRITICAL", "status": "RESOLVED_FP", "type": "SCA"},
        {"severity": "LOW", "status": "RESOLVED", "type": "SECRETS"},
    ]
    summary = summarize_defect_groups(groups)

    assert summary["defect_groups_by_severity"] == {"HIGH": 2, "CRITICAL": 1, "LOW": 1}
    assert summary["defect_groups_by_engine_type"] == {"SAST": 2, "SCA": 1, "SECRETS": 1}
    assert summary["open_defect_groups_total"] == 2  # OPEN, OPEN -- RESOLVED* excluded
    assert summary["resolved_false_positive_total"] == 1
