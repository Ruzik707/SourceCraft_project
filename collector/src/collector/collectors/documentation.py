"""Documentation category: entirely git-native (reads the shallow clone's
working tree). No platform API calls, so this collector works even before
any SourceCraft token is available.
"""
from __future__ import annotations

import re

from .base import CategoryResult, CollectorContext

_LICENSE_KEYWORDS = {
    "MIT License": "MIT",
    "Apache License": "Apache-2.0",
    "GNU GENERAL PUBLIC LICENSE": "GPL",
    "BSD": "BSD",
    "Mozilla Public License": "MPL-2.0",
}

_SECTION_PATTERNS = {
    "installation": re.compile(r"^#+\s*(installation|установка|getting started)\b", re.IGNORECASE | re.MULTILINE),
    "usage": re.compile(r"^#+\s*(usage|использование)\b", re.IGNORECASE | re.MULTILINE),
    "license": re.compile(r"^#+\s*(license|лицензия)\b", re.IGNORECASE | re.MULTILINE),
    "contributing": re.compile(r"^#+\s*(contributing|контрибьютинг)\b", re.IGNORECASE | re.MULTILINE),
    "api": re.compile(r"^#+\s*(api)\b", re.IGNORECASE | re.MULTILINE),
}


def _find_root_file(files: list[str], stems: list[str]) -> str | None:
    lower_index = {f.lower(): f for f in files if "/" not in f}
    for stem in stems:
        for candidate in lower_index:
            if candidate == stem or candidate.startswith(stem + "."):
                return lower_index[candidate]
    return None


def _find_template_dir(files: list[str], name: str) -> bool:
    needle = name.lower()
    return any(
        needle in f.lower() and (".sourcecraft/" in f.lower() or ".github/" in f.lower() or "/" not in f.lower())
        for f in files
    )


def collect(ctx: CollectorContext) -> CategoryResult:
    if ctx.git_repo is None:
        return CategoryResult(data={}, status="unavailable", errors=[
            {"category": "documentation", "source": "git", "code": "NO_CLONE", "message": "repository was not cloned"}
        ])

    files = ctx.files
    data: dict = {}

    readme_path = _find_root_file(files, ["readme"])
    data["has_readme"] = readme_path is not None
    readme_text = ctx.git_repo.read_text(readme_path) if readme_path else None
    data["readme_length_chars"] = len(readme_text) if readme_text else (0 if readme_path else None)
    data["readme_has_sections"] = (
        sorted(name for name, pattern in _SECTION_PATTERNS.items() if pattern.search(readme_text))
        if readme_text
        else ([] if readme_path else None)
    )
    data["last_readme_change_at"] = (
        ctx.git_repo.file_last_change_at(readme_path).isoformat() if readme_path else None
    )

    license_path = _find_root_file(files, ["license", "licence", "copying"])
    data["has_license"] = license_path is not None
    license_text = ctx.git_repo.read_text(license_path) if license_path else None
    data["license_type"] = next(
        (short for marker, short in _LICENSE_KEYWORDS.items() if license_text and marker.lower() in license_text.lower()),
        None,
    )

    data["has_contributing"] = _find_root_file(files, ["contributing"]) is not None
    data["has_code_of_conduct"] = _find_root_file(files, ["code_of_conduct", "code-of-conduct"]) is not None
    data["has_changelog"] = _find_root_file(files, ["changelog", "changes", "history"]) is not None

    docs_files = [f for f in files if f.lower().startswith(("docs/", "doc/"))]
    data["has_docs_dir"] = len(docs_files) > 0
    data["docs_file_count"] = len(docs_files)

    data["has_issue_templates"] = _find_template_dir(files, "issue_template")
    data["has_pr_template"] = _find_template_dir(files, "pull_request_template") or _find_template_dir(
        files, "merge_request_template"
    )

    status = "ok" if data["has_readme"] else "partial"
    return CategoryResult(data=data, status=status, errors=[])
