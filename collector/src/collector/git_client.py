"""Git-native access to a repository: everything that's plain git plumbing
(file tree, file contents, commit history, branches, tags) is fetched by
shelling out to `git` against a shallow clone, instead of guessing at a
SourceCraft REST "contents"/"commits" endpoint we have no confirmed path for.

This is deliberately dependency-light (stdlib subprocess only) so it runs
the same on the team's Windows/macOS/Linux machines and in CI.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import GitOperationError

_UNIT_SEP = "\x1f"  # ASCII unit separator, safe as a git log field delimiter

# Cloning gets its own (shorter) budget from other git calls: log/ls-tree/etc
# run against an already-cloned, size-bounded working tree and are always
# fast, but clone time scales with the remote repo's real size. Found the
# hard way batch-testing collect-open: a legitimate ~1GB+ open-source repo
# (divkit/divkit) blew well past the old 180s timeout, and because a
# TIMEOUT used to be retried with progressively MORE expensive clone
# strategies (see clone() below), one big repo could stall a whole batch
# run for many minutes instead of being skipped quickly.
_CLONE_TIMEOUT_S = 60
_OTHER_GIT_TIMEOUT_S = 180


def _clear_readonly_and_retry(func, path, exc_info) -> None:
    """shutil.rmtree error handler: git marks pack files read-only on
    Windows, which makes plain rmtree raise PermissionError. Clear the bit
    and retry the failed operation instead of giving up.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _long_path(path: Path) -> str:
    """Windows caps normal paths at 260 chars (MAX_PATH). `core.longpaths=true`
    (see clone() below) lets git CREATE files past that limit, but plain
    os/shutil calls still choke trying to DELETE them -- found live cleaning
    up a failed clone of gravity-ui/markdown-editor, whose visual-test
    snapshot filenames are long enough to trip this. The `\\\\?\\` prefix
    opts a path into Windows' real (much larger) limit. No-op elsewhere.
    """
    if os.name != "nt":
        return str(path)
    resolved = str(path.resolve())
    return resolved if resolved.startswith("\\\\?\\") else "\\\\?\\" + resolved


def _force_rmtree(path: Path, *, ignore_missing: bool = False) -> None:
    if ignore_missing and not path.exists():
        return
    shutil.rmtree(_long_path(path), onerror=_clear_readonly_and_retry)


def _run_git(args: list[str], cwd: Path | None = None, *, timeout: int = _OTHER_GIT_TIMEOUT_S) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitOperationError("git executable not found on PATH", source="git", code="GIT_NOT_FOUND") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitOperationError(f"git {' '.join(args)} timed out", source="git", code="TIMEOUT") from exc

    if proc.returncode != 0:
        # Some failures (e.g. Windows MAX_PATH errors) print one line PER
        # FILE and can run to tens of thousands of characters -- cap it so
        # one bad repo doesn't blow up every downstream consumer of this
        # message (JSON records, spreadsheets with per-cell limits, etc.).
        stderr = proc.stderr.strip()
        if len(stderr) > 2000:
            stderr = stderr[:2000] + f"... [truncated, {len(stderr)} chars total]"
        raise GitOperationError(
            f"git {' '.join(args)} failed: {stderr}",
            source="git",
            code="GIT_NONZERO_EXIT",
        )
    return proc.stdout


@dataclass(frozen=True)
class Commit:
    sha: str
    author_email: str
    authored_at: datetime


class GitRepo:
    """A shallow local clone of one remote repository, ready for read-only
    inspection. Call `GitRepo.clone(...)` rather than constructing directly.
    """

    def __init__(self, path: Path):
        self.path = path
        self._is_empty: bool | None = None

    def is_empty(self) -> bool:
        """True when the clone has no commits at all -- `git clone` itself
        succeeds fine for such a repo, but HEAD doesn't resolve to a real
        commit, so anything that needs one (`ls-tree HEAD`, `log`, ...)
        fails with "fatal: Not a valid object name HEAD" or similar. Found
        this crashing whole-repo processing (not just one category) on a
        batch run: with 27,000+ public repos there are, unsurprisingly,
        plenty of genuinely empty ones (fresh test/hackathon placeholders).
        Cached after the first check -- emptiness can't change mid-run since
        we never write to the clone.
        """
        if self._is_empty is None:
            try:
                _run_git(["rev-parse", "--verify", "-q", "HEAD"], cwd=self.path)
                self._is_empty = False
            except GitOperationError:
                self._is_empty = True
        return self._is_empty

    @classmethod
    def clone(cls, clone_url: str, dest_dir: Path, *, shallow_since: str) -> "GitRepo":
        _force_rmtree(dest_dir, ignore_missing=True)
        dest_dir.parent.mkdir(parents=True, exist_ok=True)

        # --shallow-since occasionally fails FAST on repos with unusual
        # history shapes ("error processing shallow info") -- a known git
        # quirk, not something our path/URL handling can avoid. Falling back
        # to a plain depth-limited clone, then a full clone, handles that.
        #
        # But a TIMEOUT is a different situation and must NOT escalate the
        # same way: it means the repo is just large/slow, and retrying with
        # a progressively bigger clone (depth 500, then unbounded) makes a
        # slow case slower, not better. Found this the hard way batch-testing
        # collect-open: a real ~1GB+ open-source repo stalled an entire
        # 20-repo sample run for many minutes before being force-stopped.
        # So: GIT_NONZERO_EXIT escalates to the next attempt; TIMEOUT (and
        # GIT_NOT_FOUND) give up immediately.
        # -c core.longpaths=true: found live batch-testing collect-open --
        # gravity-ui/markdown-editor has deeply nested visual-test snapshot
        # files whose full path exceeds Windows' default 260-char MAX_PATH,
        # so plain `git clone` fails outright with "unable to create file"
        # (one such error per file -- can be dozens, filling the whole error
        # message). This is the standard, well-known fix on Windows; it's a
        # no-op on macOS/Linux.
        attempts = [
            (["-c", "core.longpaths=true", "clone", "--quiet", "--no-single-branch", f"--shallow-since={shallow_since}", clone_url, str(dest_dir)], _CLONE_TIMEOUT_S),
            (["-c", "core.longpaths=true", "clone", "--quiet", "--no-single-branch", "--depth", "500", clone_url, str(dest_dir)], _CLONE_TIMEOUT_S),
            (["-c", "core.longpaths=true", "clone", "--quiet", clone_url, str(dest_dir)], _CLONE_TIMEOUT_S),
        ]
        last_error: GitOperationError | None = None
        for args, timeout in attempts:
            try:
                _run_git(args, timeout=timeout)
                return cls(dest_dir)
            except GitOperationError as exc:
                last_error = exc
                _force_rmtree(dest_dir, ignore_missing=True)
                if exc.code != "GIT_NONZERO_EXIT":
                    break
        raise last_error  # type: ignore[misc]

    def cleanup(self) -> None:
        _force_rmtree(self.path, ignore_missing=True)

    def current_branch(self) -> str | None:
        if self.is_empty():
            return None
        out = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=self.path).strip()
        return out or None

    # --- tree / file access -------------------------------------------------

    def list_files(self) -> list[str]:
        if self.is_empty():
            return []
        out = _run_git(["ls-tree", "-r", "--name-only", "HEAD"], cwd=self.path)
        return [line for line in out.splitlines() if line]

    def read_text(self, relpath: str, max_bytes: int = 2_000_000) -> str | None:
        full = self.path / relpath
        if not full.is_file():
            return None
        data = full.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="replace")

    def file_line_count(self, relpath: str) -> int | None:
        text = self.read_text(relpath)
        if text is None:
            return None
        return text.count("\n") + (0 if text.endswith("\n") or text == "" else 1)

    # --- history -------------------------------------------------------------

    def log(self, since: str | None = None) -> list[Commit]:
        if self.is_empty():
            return []
        args = ["log", "--date=iso-strict", f"--pretty=format:%H{_UNIT_SEP}%ae{_UNIT_SEP}%ad"]
        if since:
            args.insert(1, f"--since={since}")
        out = _run_git(args, cwd=self.path)
        commits: list[Commit] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            sha, email, iso_date = line.split(_UNIT_SEP)
            commits.append(Commit(sha=sha, author_email=email, authored_at=datetime.fromisoformat(iso_date)))
        return commits

    def last_commit_at(self) -> datetime | None:
        commits = self.log()
        return commits[0].authored_at if commits else None

    def file_last_change_at(self, relpath: str) -> datetime | None:
        """Best-effort: only sees changes within the shallow-clone window
        (see COLLECTOR_GIT_SHALLOW_SINCE). A file untouched since before that
        window returns None here even though it exists -- that's a known
        trade-off for not doing a full clone.
        """
        out = _run_git(["log", "-1", "--date=iso-strict", "--pretty=format:%ad", "--", relpath], cwd=self.path)
        out = out.strip()
        return datetime.fromisoformat(out) if out else None

    # --- refs ------------------------------------------------------------

    def remote_branch_count(self, clone_url: str) -> int | None:
        try:
            out = _run_git(["ls-remote", "--heads", clone_url])
        except GitOperationError:
            return None
        return sum(1 for line in out.splitlines() if line.strip())

    def remote_tag_count(self, clone_url: str) -> int | None:
        try:
            out = _run_git(["ls-remote", "--tags", clone_url])
        except GitOperationError:
            return None
        return sum(1 for line in out.splitlines() if line.strip())


_TODO_PATTERN = re.compile(r"\b(TODO|FIXME|HACK)\b", re.IGNORECASE)
_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".wasm", ".so", ".dll",
    ".exe", ".class", ".jar", ".lock",
}
_VENDOR_DIR_MARKERS = {"node_modules", "vendor", ".git", "dist", "build", "__pycache__", ".venv", "venv"}


def is_countable_source_file(relpath: str) -> bool:
    parts = Path(relpath).parts
    if any(p in _VENDOR_DIR_MARKERS for p in parts):
        return False
    return Path(relpath).suffix.lower() not in _BINARY_EXT


def has_todo_marker(text: str) -> bool:
    """Same word-boundary rule as scan_todos()'s counting, exposed so callers
    that only need a yes/no (e.g. finding which files to check for TODO age)
    don't fall back to a naive substring check -- that previously matched
    "HACK" inside unrelated words like "hackathon"/"hackaton".
    """
    return _TODO_PATTERN.search(text) is not None


def scan_todos(repo: GitRepo, files: list[str]) -> dict[str, int]:
    counts = {"TODO": 0, "FIXME": 0, "HACK": 0}
    for relpath in files:
        if not is_countable_source_file(relpath):
            continue
        text = repo.read_text(relpath)
        if text is None:
            continue
        for match in _TODO_PATTERN.finditer(text):
            counts[match.group(1).upper()] += 1
    return counts
