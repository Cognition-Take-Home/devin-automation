"""Command-line entrypoint for the dependency automation.

Subcommands:
  list   - print the top-level dependencies discovered in the target repo
  check  - report which dependencies are outdated (no Devin sessions created)
  run    - create Devin sessions for outdated dependencies (use --dry-run to preview)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .config import Config
from .metrics import render_markdown, render_text
from .models import OutdatedDependency, RunReport
from .runner import Runner


def _build_runner(args: argparse.Namespace) -> Runner:
    config = Config.from_file(args.config)
    if args.target_repo_path:
        config.target_repo_path = args.target_repo_path
    if args.policy:
        config.trigger_policy = args.policy
    return Runner(config)


def _print_outdated(outdated: list[OutdatedDependency], as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "name": od.name,
                        "ecosystem": od.ecosystem.value,
                        "manifest": od.dependency.manifest,
                        "constraint": od.dependency.constraint,
                        "current": od.dependency.current_version,
                        "latest": od.latest_version,
                        "update_kind": od.update_kind.value,
                        "requires_manifest_change": od.requires_manifest_change,
                    }
                    for od in outdated
                ],
                indent=2,
            )
        )
        return
    if not outdated:
        print("All tracked dependencies are up to date.")
        return
    for od in outdated:
        flag = "needs-bump" if od.requires_manifest_change else "newer-available"
        current = od.dependency.current_version or od.dependency.constraint
        print(
            f"[{od.ecosystem.value}] {od.name}: {current} "
            f"-> {od.latest_version} ({od.update_kind.value}, {flag})"
        )


def _cmd_list(args: argparse.Namespace) -> int:
    runner = _build_runner(args)
    deps = runner.collect_dependencies()
    for dep in deps:
        print(f"[{dep.ecosystem.value}] {dep.name} {dep.constraint} ({dep.manifest})")
    print(f"\n{len(deps)} top-level dependencies.", file=sys.stderr)
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    runner = _build_runner(args)
    report = RunReport()
    outdated = runner.find_outdated(report)
    _print_outdated(outdated, args.json)
    if report.errors and not args.json:
        print(f"\n{len(report.errors)} lookup error(s):", file=sys.stderr)
        for err in report.errors:
            print(f"  - {err}", file=sys.stderr)
    print(
        f"\nChecked {report.checked}, outdated {len(outdated)}.",
        file=sys.stderr,
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    runner = _build_runner(args)
    report = runner.run(dry_run=args.dry_run)
    for result in report.results:
        od = result.dependency
        if result.triggered:
            print(f"TRIGGERED {od.name} -> {od.latest_version}: {result.session_url}")
        else:
            print(f"skipped   {od.name} -> {od.latest_version}: {result.skipped_reason}")
    print(
        f"\nChecked {report.checked}, outdated {len(report.outdated)}, "
        f"triggered {len(report.triggered)}.",
        file=sys.stderr,
    )
    if report.errors:
        for err in report.errors:
            print(f"  lookup error: {err}", file=sys.stderr)
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
    parser.add_argument(
        "--policy",
        choices=["out-of-range", "any-newer"],
        help="override trigger policy",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list discovered top-level dependencies")
    p_list.set_defaults(func=_cmd_list)

    p_check = sub.add_parser("check", help="report outdated dependencies")
    p_check.add_argument("--json", action="store_true", help="emit JSON")
    p_check.set_defaults(func=_cmd_check)

    p_run = sub.add_parser("run", help="trigger Devin sessions for outdated dependencies")
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help="discover and report without creating Devin sessions",
    )
    p_run.set_defaults(func=_cmd_run)

    p_report = sub.add_parser(
        "report",
        help="summarise effectiveness: outcomes, success rate, throughput, drift",
    )
    p_report.add_argument(
        "--sync",
        action="store_true",
        help="refresh live session status + PRs from the Devin API before reporting",
    )
    p_report.add_argument(
        "--coverage",
        action="store_true",
        help="also compute current drift (how many tracked deps are behind)",
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
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
