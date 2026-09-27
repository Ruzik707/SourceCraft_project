"""
Usage:
    python -m collector collect --owner some-org --name some-repo \
        --clone-url https://sourcecraft.dev/some-org/some-repo.git [--gitrepo-id UUID]

    python -m collector collect-batch --repos-file config/repos.example.yaml

    python -m collector discover [--org some-org]
    python -m collector collect-open --limit 20 [--org some-org] [--resume]
    python -m collector collect-open --limit 100000 --oldest-first --max-minutes 45

`discover`/`collect-open` enumerate public repos via the platform API
(GET /repos, or GET /orgs/{org}/repos with --org) -- see discovery.py.
`discover` just lists what it found; `collect-open` runs the full
collection pipeline on the first `--limit` public repos found, up to
`--concurrency` (default 4) at once. `--limit` is required on purpose:
there are ~27,600 public repos platform-wide (2026-09-19) and, based on
real measured per-repo timings (median ~7s, mean ~33s pulled up by a few
large/slow repos), cloning+collecting all of them sequentially would take
2-10+ days -- pick a real batch size, don't default into scanning the
whole platform from a single run. Raise --concurrency for more throughput,
but remember every worker is a real git clone plus several API calls
against SourceCraft's shared infrastructure, not free parallelism.

All collection subcommands write to <output_dir>/<owner>__<name>/<timestamp>.json
and .../latest.json (see storage.py), and print a one-line summary per repo.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .aggregator import collect_repo
from .config import Settings, load_settings
from .discovery import discover_open_repos
from .endpoint_registry import load_registry
from .errors import CollectorError
from .platform_client import PlatformClient
from .repo_ref import RepoRef, load_repo_refs
from .schema_validate import validate_record
from .storage import write_record


def _discover_or_none(settings: Settings, org_slug: str | None) -> list[RepoRef] | None:
    platform = PlatformClient(load_registry()["platform_api"], token=settings.sourcecraft_token, cli_path=settings.sourcecraft_cli_path)
    try:
        return discover_open_repos(platform, org_slug=org_slug)
    except CollectorError as exc:
        print(f"discover failed: {exc.message}", file=sys.stderr)
        if not settings.sourcecraft_token:
            print(
                "hint: SOURCECRAFT_TOKEN is not set. Copy .env.example to .env, "
                "fill in a Personal Access Token (Home -> Access -> Personal access "
                "tokens on sourcecraft.dev), and re-run.",
                file=sys.stderr,
            )
        return None


def _filter_resume(refs: list[RepoRef], output_dir: Path) -> tuple[list[RepoRef], int]:
    """Drops any repo that already has output/<workdir_name>/latest.json.
    Returns (remaining_refs, skipped_count).
    """
    remaining = [r for r in refs if not (output_dir / r.workdir_name / "latest.json").exists()]
    return remaining, len(refs) - len(remaining)


def _collected_at(output_dir: Path, repo_ref: RepoRef) -> str:
    """`collection.collected_at` of the repo's latest.json, or "" if there is
    none (or it's unreadable) -- so never-collected repos sort first.
    """
    try:
        with open(output_dir / repo_ref.workdir_name / "latest.json", encoding="utf-8") as fh:
            return json.load(fh)["collection"]["collected_at"] or ""
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def _order_oldest_first(refs: list[RepoRef], output_dir: Path) -> list[RepoRef]:
    """Never-collected repos first (in discovery order), then the stalest
    ones. Reads collected_at from the JSON rather than file mtime: in CI the
    output dir is restored from an archive, so mtimes mean nothing there.
    ISO-8601 UTC strings from the same writer sort chronologically as text.
    """
    return sorted(refs, key=lambda r: _collected_at(output_dir, r))


_print_lock = threading.Lock()


def _run_one(repo_ref: RepoRef, args: argparse.Namespace) -> int:
    # Each call loads its own Settings/registries and the aggregator opens
    # its own PlatformClient/AppSecClient/git clone dir (named after
    # repo_ref.workdir_name, unique per repo) -- no shared mutable state
    # between repos, so this is safe to call from multiple threads at once
    # (see collect-open's ThreadPoolExecutor below).
    settings = load_settings()
    registries = load_registry()
    record = collect_repo(repo_ref, settings, registries, keep_workdir=args.keep_workdir)

    problems = [] if args.no_validate else validate_record(record)

    snapshot_path, latest_path = write_record(record, repo_ref, settings.output_dir)
    statuses = record["collection"]["category_status"]
    summary = ", ".join(f"{cat}={status}" for cat, status in statuses.items())
    # flush=True matters for collect-open: stdout is block-buffered when not
    # a tty (e.g. redirected to a background-task log file), so without it
    # per-repo progress lines can sit invisible in the buffer for a long
    # batch run instead of showing up as each repo finishes. The lock keeps
    # concurrent workers' lines from interleaving into garbled output.
    with _print_lock:
        if problems:
            print(f"[{repo_ref.full_path}] SCHEMA VALIDATION FAILED:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
        print(f"[{repo_ref.full_path}] {summary} -> {latest_path}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="collector")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--keep-workdir", action="store_true", help="don't delete the shallow clone after collection")
    common.add_argument("--no-validate", action="store_true", help="skip JSON Schema validation of the output")

    one = sub.add_parser("collect", parents=[common], help="collect data for a single repo")
    one.add_argument("--owner", required=True)
    one.add_argument("--name", required=True)
    one.add_argument("--clone-url", required=True)
    one.add_argument("--gitrepo-id", default=None, help="AppSec `gitRepo` id/UUID; omit to skip the security category")

    batch = sub.add_parser("collect-batch", parents=[common], help="collect data for every repo in a YAML file")
    batch.add_argument("--repos-file", required=True, type=Path)

    discover = sub.add_parser("discover", help="list public repos found via the platform API, without collecting")
    discover.add_argument("--org", default=None, help="restrict to one org's repos; omit for the global /repos listing")

    collect_open = sub.add_parser("collect-open", parents=[common], help="discover public repos, then collect each")
    collect_open.add_argument("--org", default=None)
    collect_open.add_argument(
        "--limit", required=True, type=int,
        help="max number of discovered repos to collect (required on purpose -- there are ~27,600 "
             "public repos platform-wide as of 2026-09-19; pass a large number explicitly if you "
             "really mean 'all of them', don't default into it)",
    )
    collect_open.add_argument(
        "--concurrency", type=int, default=4,
        help="how many repos to collect at once (default 4). Each one is a real git clone plus "
             "several API calls against SourceCraft's shared infrastructure -- keep this modest "
             "rather than maximizing throughput, to stay a good citizen on someone else's servers.",
    )
    collect_open.add_argument(
        "--resume", action="store_true",
        help="skip repos that already have output/<owner>__<name>/latest.json. There's no "
             "mid-run checkpoint (the discovery order is deterministic, but a restart otherwise "
             "walks it from the top again) -- pass this after a restart to pick up where a "
             "previous run left off instead of re-collecting everything already done.",
    )
    collect_open.add_argument(
        "--oldest-first", action="store_true",
        help="before applying --limit, order repos as: never collected first, then by the "
             "collected_at of their latest.json, oldest first. Repeated runs with this flag "
             "walk the whole platform and then keep refreshing the stalest records -- this is "
             "what the scheduled CI refresh uses.",
    )
    collect_open.add_argument(
        "--max-minutes", type=float, default=None,
        help="time budget for the batch: once it's spent, repos that haven't started yet are "
             "skipped (not counted as failures), so a CI step ends before its hard timeout "
             "and later steps still get to export what was collected.",
    )

    args = parser.parse_args(argv)

    if args.command == "collect":
        repo_ref = RepoRef(owner=args.owner, name=args.name, clone_url=args.clone_url, gitrepo_id=args.gitrepo_id)
        return _run_one(repo_ref, args)

    if args.command == "collect-batch":
        exit_code = 0
        for repo_ref in load_repo_refs(args.repos_file):
            exit_code |= _run_one(repo_ref, args)
        return exit_code

    if args.command == "discover":
        settings = load_settings()
        refs = _discover_or_none(settings, args.org)
        if refs is None:
            return 1
        for ref in refs:
            print(f"{ref.full_path}\t{ref.clone_url}\tgitrepo_id={ref.gitrepo_id}")
        print(f"\n{len(refs)} public repo(s) found.", file=sys.stderr)
        return 0

    if args.command == "collect-open":
        settings = load_settings()
        refs = _discover_or_none(settings, args.org)
        if refs is None:
            return 1
        if args.oldest_first:
            refs = _order_oldest_first(refs, settings.output_dir)
        if len(refs) > args.limit:
            print(f"found {len(refs)} public repos, collecting the first {args.limit} (--limit)", file=sys.stderr)
        refs = refs[: args.limit]

        if args.resume:
            refs, skipped = _filter_resume(refs, settings.output_dir)
            if skipped:
                print(f"--resume: skipping {skipped} already-collected repo(s), {len(refs)} left to do", file=sys.stderr)

        print(f"collecting {len(refs)} repos with concurrency={args.concurrency}", file=sys.stderr)

        deadline = None if args.max_minutes is None else time.monotonic() + args.max_minutes * 60
        out_of_time: list[RepoRef] = []

        def run_within_budget(repo_ref: RepoRef) -> int:
            if deadline is not None and time.monotonic() > deadline:
                with _print_lock:
                    out_of_time.append(repo_ref)
                return 0
            return _run_one(repo_ref, args)

        exit_code = 0
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {pool.submit(run_within_budget, repo_ref): repo_ref for repo_ref in refs}
            for future in as_completed(futures):
                repo_ref = futures[future]
                try:
                    exit_code |= future.result()
                except Exception as exc:  # noqa: BLE001 -- one repo's crash must not lose the rest of the batch
                    with _print_lock:
                        print(f"[{repo_ref.full_path}] CRASHED: {exc}", file=sys.stderr, flush=True)
                    exit_code = 1
        if out_of_time:
            print(f"--max-minutes: time budget spent, {len(out_of_time)} repo(s) left for the next run", file=sys.stderr)
        return exit_code

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
