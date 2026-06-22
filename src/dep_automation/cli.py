"""Command-line entrypoint for the dependency usage-optimization automation.

Subcommands:
  list      - print the top-level dependencies discovered in the target repo
  shortlist - show the candidates this run would put in front of Devin (no session)
  optimize  - run the nightly optimization: shortlist deps, create ONE Devin session
              that picks one and improves how the repo uses it (use --dry-run to preview)
  report    - summarise effectiveness: outcomes, success rate, throughput, coverage
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import Config
from .metrics import render_markdown, render_text
from .runner import Runner
from .usage import RipgrepNotFound


def _build_runner(args: argparse.Namespace) -> Runner:
    config = Config.from_file(args.config)
    if args.target_repo_path:
        config.target_repo_path = args.target_repo_path
    return Runner(config)


def _cmd_list(args: argparse.Namespace) -> int:
    runner = _build_runner(args)
    deps = runner.collect_dependencies()
    for dep in deps:
        print(f"[{dep.ecosystem.value}] {dep.name} {dep.constraint} ({dep.manifest})")
    print(f"\n{len(deps)} top-level dependencies.", file=sys.stderr)
    return 0


def _cmd_shortlist(args: argparse.Namespace) -> int:
    runner = _build_runner(args)
    candidates = runner.shortlist()
    if not candidates:
        print("No candidate dependencies (all in cooldown or filtered out).")
        return 0
    print(f"Shortlist ({len(candidates)} candidate(s), most-used first):")
    for c in candidates:
        print(f"  [{c.ecosystem.value}] {c.name}  (~{c.usage} usages, {c.dependency.constraint})")
    return 0


def _cmd_optimize(args: argparse.Namespace) -> int:
    runner = _build_runner(args)
    result = runner.optimize(dry_run=args.dry_run)

    print("Candidates considered:")
    for c in result.candidates:
        print(f"  [{c.ecosystem.value}] {c.name} (~{c.usage} usages)")
    if result.triggered:
        print(f"\nTRIGGERED optimization session: {result.session_url}")
    else:
        print(f"\nNo session created: {result.skipped_reason}")
    for err in result.errors:
        print(f"  error: {err}", file=sys.stderr)
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    runner = _build_runner(args)
    if args.sync:
        synced = runner.sync_statuses()
        print(f"Synced {synced} session(s) from the Devin API.", file=sys.stderr)
    report = runner.build_report(coverage=args.coverage)

    if args.json:
        print(report.to_json())
    elif args.markdown:
        print(render_markdown(report))
    else:
        print(render_text(report))

    # When running in GitHub Actions, also publish the markdown report to the run summary
    # so an engineering leader sees it directly in the Actions UI.
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(render_markdown(report) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dep-automation", description=__doc__)
    parser.add_argument("-c", "--config", default="config.yaml", help="path to config YAML")
    parser.add_argument("--target-repo-path", help="override the local path to the target repo")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list discovered top-level dependencies")
    p_list.set_defaults(func=_cmd_list)

    p_shortlist = sub.add_parser(
        "shortlist", help="show the optimization candidates for this run (no session)"
    )
    p_shortlist.set_defaults(func=_cmd_shortlist)

    p_opt = sub.add_parser(
        "optimize",
        help="run the nightly optimization: shortlist deps and create one Devin session",
    )
    p_opt.add_argument(
        "--dry-run",
        action="store_true",
        help="shortlist and report without creating a Devin session",
    )
    p_opt.set_defaults(func=_cmd_optimize)

    p_report = sub.add_parser(
        "report",
        help="summarise effectiveness: outcomes, success rate, throughput, coverage",
    )
    p_report.add_argument(
        "--sync",
        action="store_true",
        help="refresh live session status + PRs from the Devin API before reporting",
    )
    p_report.add_argument(
        "--coverage",
        action="store_true",
        help="also compute coverage (share of deps optimized at least once)",
    )
    fmt = p_report.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="emit JSON")
    fmt.add_argument("--markdown", action="store_true", help="emit Markdown")
    p_report.set_defaults(func=_cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except RipgrepNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
