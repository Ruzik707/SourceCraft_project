"""Environment-driven configuration. No secrets ever hardcoded here."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    sourcecraft_api_base_url: str = field(
        default_factory=lambda: os.getenv("SOURCECRAFT_API_BASE_URL", "https://api.sourcecraft.tech")
    )
    sourcecraft_token: str | None = field(default_factory=lambda: os.getenv("SOURCECRAFT_TOKEN") or None)
    sourcecraft_cli_path: str = field(default_factory=lambda: os.getenv("SOURCECRAFT_CLI_PATH", "src"))

    appsec_api_base_url: str = field(
        default_factory=lambda: os.getenv("APPSEC_API_BASE_URL", "https://appsec.sourcecraft.tech")
    )
    appsec_token: str | None = field(default_factory=lambda: os.getenv("APPSEC_TOKEN") or None)
    appsec_curl_config_path: str | None = field(
        default_factory=lambda: os.getenv("APPSEC_CURL_CONFIG_PATH") or None
    )

    workdir: Path = field(default_factory=lambda: Path(os.getenv("COLLECTOR_WORKDIR", ".workdir")))
    git_shallow_since: str = field(
        default_factory=lambda: os.getenv("COLLECTOR_GIT_SHALLOW_SINCE", "366 days ago")
    )
    output_dir: Path = field(default_factory=lambda: Path(os.getenv("COLLECTOR_OUTPUT_DIR", "output")))


def load_settings() -> Settings:
    return Settings()
