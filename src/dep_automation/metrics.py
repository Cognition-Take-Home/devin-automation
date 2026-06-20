"""Analytics / reporting layer.

Turns the persisted upgrade state (and an optional run history + current drift
snapshot) into metrics that answer a single question for an engineering leader:
**"how do I know this is working?"**

The headline signals are:
- *Outcomes* of every upgrade the system started: how many produced a merged PR, an
  open PR (awaiting review), are still in flight, or ended without a PR.
- *Success rate*: share of finished sessions that produced a PR.
- *Drift / coverage*: how many tracked dependencies are currently behind (the backlog
  the system is working down).
- *Throughput*: sessions started and PRs produced over time, from the run history.
- *Cost*: ACUs consumed.

This module is pure (no I/O); the CLI and runner feed it data and render the result.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from .state import StateEntry

# Devin session statuses that mean the session is still doing (or could resume) work.
_ACTIVE_STATUSES = {"running", "working", "resumed", "starting", "queued"}
# Statuses that mean a human needs to act for the session to make progress.
_BLOCKED_STATUSES = {"blocked"}


class Outcome(StrEnum):
    """Bucket a tracked upgrade falls into, derived from its session + PR state."""

    PR_MERGED = "pr_merged"  # success, landed
    PR_OPEN = "pr_open"  # success, awaiting human review
    ACTIVE = "active"  # session still working
    BLOCKED = "blocked"  # session needs human input
    COMPLETED_NO_PR = "completed_no_pr"  # ended without producing a PR
    UNKNOWN = "unknown"  # triggered but never synced


def classify(entry: StateEntry) -> Outcome:
    pr_state = (entry.pr_state or "").lower()
    if pr_state == "merged":
        return Outcome.PR_MERGED
    if entry.pr_url:
        return Outcome.PR_OPEN
    status = (entry.status or "").lower()
    if not status:
        return Outcome.UNKNOWN
    if status in _BLOCKED_STATUSES:
        return Outcome.BLOCKED
    if status in _ACTIVE_STATUSES:
        return Outcome.ACTIVE
    # finished / expired / suspended / stopped with no PR
    return Outcome.COMPLETED_NO_PR


# Outcomes that represent a session that has come to rest (for success-rate math).
_TERMINAL = {Outcome.PR_MERGED, Outcome.PR_OPEN, Outcome.COMPLETED_NO_PR}
_PRODUCED_PR = {Outcome.PR_MERGED, Outcome.PR_OPEN}


@dataclass
class Coverage:
    """Snapshot of how far behind the tracked dependencies currently are."""

    checked: int
    outdated: int

    @property
    def up_to_date(self) -> int:
        return max(self.checked - self.outdated, 0)

    @property
    def pct_up_to_date(self) -> float:
        return round(100.0 * self.up_to_date / self.checked, 1) if self.checked else 0.0


@dataclass
class Report:
    generated_at: str
    entries: list[StateEntry]
    coverage: Coverage | None = None
    history: list[dict] = field(default_factory=list)

    # -- derived aggregates ------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def by_outcome(self) -> dict[Outcome, int]:
        c: Counter[Outcome] = Counter(classify(e) for e in self.entries)
        return {o: c.get(o, 0) for o in Outcome}

    @property
    def by_ecosystem(self) -> dict[str, int]:
        return dict(Counter(e.ecosystem for e in self.entries))

    @property
    def by_update_kind(self) -> dict[str, int]:
        return dict(Counter((e.update_kind or "unknown") for e in self.entries))

    @property
    def prs_open(self) -> int:
        return self.by_outcome[Outcome.PR_OPEN]

    @property
    def prs_merged(self) -> int:
        return self.by_outcome[Outcome.PR_MERGED]

    @property
    def active(self) -> int:
        return self.by_outcome[Outcome.ACTIVE] + self.by_outcome[Outcome.BLOCKED]

    @property
    def completed(self) -> int:
        return sum(self.by_outcome[o] for o in _TERMINAL)

    @property
    def success_rate(self) -> float | None:
        """Share of *finished* sessions that produced a PR (None if none finished)."""
        if self.completed == 0:
            return None
        produced = sum(self.by_outcome[o] for o in _PRODUCED_PR)
        return round(100.0 * produced / self.completed, 1)

    @property
    def total_acus(self) -> float:
        return round(sum(e.acus_consumed or 0.0 for e in self.entries), 2)

    @property
    def history_totals(self) -> dict[str, int]:
        keys = ("checked", "outdated", "triggered", "errors")
        return {k: sum(int(r.get(k, 0)) for r in self.history) for k in keys}

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict:
        sr = self.success_rate
        out = {
            "generated_at": self.generated_at,
            "totals": {
                "tracked_upgrades": self.total,
                "active": self.active,
                "completed": self.completed,
                "prs_open": self.prs_open,
                "prs_merged": self.prs_merged,
                "success_rate_pct": sr,
                "acus_consumed": self.total_acus,
            },
            "by_outcome": {o.value: n for o, n in self.by_outcome.items()},
            "by_ecosystem": self.by_ecosystem,
            "by_update_kind": self.by_update_kind,
            "runs": {"count": len(self.history), **self.history_totals},
            "upgrades": [
                {
                    "name": e.name,
                    "ecosystem": e.ecosystem,
                    "version": e.version,
                    "update_kind": e.update_kind,
                    "outcome": classify(e).value,
                    "status": e.status,
                    "pr_url": e.pr_url,
                    "pr_state": e.pr_state,
                    "session_url": e.session_url,
                    "triggered_at": e.triggered_at,
                    "acus_consumed": e.acus_consumed,
                }
                for e in self.entries
            ],
        }
        if self.coverage is not None:
            out["coverage"] = {
                "checked": self.coverage.checked,
                "outdated": self.coverage.outdated,
                "up_to_date": self.coverage.up_to_date,
                "pct_up_to_date": self.coverage.pct_up_to_date,
            }
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def build_report(
    entries: list[StateEntry],
    *,
    coverage: Coverage | None = None,
    history: list[dict] | None = None,
    now: datetime | None = None,
) -> Report:
    return Report(
        generated_at=(now or datetime.now(UTC)).isoformat(),
        entries=list(entries),
        coverage=coverage,
        history=list(history or []),
    )


# -- rendering -------------------------------------------------------------

_OUTCOME_LABEL = {
    Outcome.PR_MERGED: "PR merged",
    Outcome.PR_OPEN: "PR open (review)",
    Outcome.ACTIVE: "active",
    Outcome.BLOCKED: "blocked (needs input)",
    Outcome.COMPLETED_NO_PR: "ended, no PR",
    Outcome.UNKNOWN: "unknown (not synced)",
}


def _fmt_pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v}%"


def render_text(report: Report) -> str:
    lines: list[str] = []
    lines.append(f"Dependency automation report  (generated {report.generated_at})")
    lines.append("=" * 60)
    if report.coverage is not None:
        cov = report.coverage
        lines.append(
            f"Coverage: {cov.up_to_date}/{cov.checked} deps up to date "
            f"({cov.pct_up_to_date}%), {cov.outdated} behind"
        )
    lines.append(
        f"Upgrades tracked: {report.total}  |  active: {report.active}  "
        f"|  completed: {report.completed}"
    )
    lines.append(
        f"PRs: {report.prs_open} open, {report.prs_merged} merged  "
        f"|  success rate: {_fmt_pct(report.success_rate)}  "
        f"|  ACUs: {report.total_acus}"
    )
    lines.append("")
    lines.append("By outcome:")
    for outcome, n in report.by_outcome.items():
        if n:
            lines.append(f"  {_OUTCOME_LABEL[outcome]:<22} {n}")
    if report.history:
        h = report.history_totals
        lines.append("")
        lines.append(
            f"Across {len(report.history)} run(s): checked {h['checked']}, "
            f"outdated {h['outdated']}, triggered {h['triggered']}, errors {h['errors']}"
        )
    lines.append("")
    lines.append("Upgrades:")
    for e in report.entries:
        oc = _OUTCOME_LABEL[classify(e)]
        suffix = f"  {e.pr_url}" if e.pr_url else (f"  {e.session_url}" if e.session_url else "")
        lines.append(
            f"  [{e.ecosystem}] {e.name} -> {e.version} "
            f"({e.update_kind or 'unknown'}): {oc}{suffix}"
        )
    return "\n".join(lines)


def render_markdown(report: Report) -> str:
    lines: list[str] = []
    lines.append("## Dependency automation report")
    lines.append("")
    lines.append(f"_Generated {report.generated_at}_")
    lines.append("")
    if report.coverage is not None:
        cov = report.coverage
        lines.append(
            f"**Coverage:** {cov.up_to_date}/{cov.checked} dependencies up to date "
            f"(**{cov.pct_up_to_date}%**) — {cov.outdated} behind"
        )
        lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Upgrades tracked | {report.total} |")
    lines.append(f"| Active sessions | {report.active} |")
    lines.append(f"| Completed | {report.completed} |")
    lines.append(f"| PRs open (awaiting review) | {report.prs_open} |")
    lines.append(f"| PRs merged | {report.prs_merged} |")
    lines.append(f"| Success rate (finished → PR) | {_fmt_pct(report.success_rate)} |")
    lines.append(f"| ACUs consumed | {report.total_acus} |")
    if report.history:
        h = report.history_totals
        lines.append(f"| Runs recorded | {len(report.history)} |")
        lines.append(f"| Sessions triggered (all runs) | {h['triggered']} |")
    lines.append("")
    lines.append("### Upgrades")
    lines.append("")
    lines.append("| Package | Version | Size | Outcome | Link |")
    lines.append("| --- | --- | --- | --- | --- |")
    for e in report.entries:
        oc = _OUTCOME_LABEL[classify(e)]
        link = ""
        if e.pr_url:
            link = f"[PR]({e.pr_url})"
        elif e.session_url:
            link = f"[session]({e.session_url})"
        lines.append(
            f"| `{e.name}` ({e.ecosystem}) | {e.version} | "
            f"{e.update_kind or 'unknown'} | {oc} | {link} |"
        )
    lines.append("")
    return "\n".join(lines)
