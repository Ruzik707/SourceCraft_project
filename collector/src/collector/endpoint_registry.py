"""Loads config/endpoints.yaml and resolves logical operation names to
concrete request templates. Keeping this out of the client code means the
team can correct a path (or flip verified: false -> true) without touching
Python once real API access is confirmed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "endpoints.yaml"


@dataclass(frozen=True)
class Operation:
    key: str
    method: str
    path_template: str
    pagination: str  # "none" | "cursor"
    verified: bool
    source: str
    list_key: str | None = None  # cursor pagination: dict key holding the array, e.g. "issues"

    def resolve_path(self, **params: str) -> str:
        try:
            return self.path_template.format(**params)
        except KeyError as exc:
            raise ValueError(
                f"operation '{self.key}' needs path param {exc}, got {list(params)}"
            ) from exc


class EndpointRegistry:
    def __init__(self, api_name: str, raw: dict):
        self.api_name = api_name
        self.base_url_env: str = raw["base_url_env"]
        self.default_base_url: str = raw["default_base_url"]
        self.auth: str = raw.get("auth", "unspecified")
        self.token_env: str | None = raw.get("token_env")
        self._operations = {
            key: Operation(
                key=key,
                method=op["method"],
                path_template=op["path"],
                pagination=op.get("pagination", "none"),
                verified=bool(op.get("verified", False)),
                source=op.get("source", ""),
                list_key=op.get("list_key"),
            )
            for key, op in raw.get("operations", {}).items()
        }

    def get(self, key: str) -> Operation:
        try:
            return self._operations[key]
        except KeyError:
            raise KeyError(
                f"unknown {self.api_name} operation '{key}'. "
                f"Known operations: {sorted(self._operations)}"
            ) from None

    def unverified_keys(self) -> list[str]:
        return sorted(k for k, op in self._operations.items() if not op.verified)


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> dict[str, EndpointRegistry]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return {name: EndpointRegistry(name, block) for name, block in raw.items()}
