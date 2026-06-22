"""Analytics / reporting layer.

Turns the persisted optimization sessions (and an optional run history + coverage
snapshot) into metrics that answer a single question for an engineering leader:
**"how do I know this is working?"**

The headline signals are:
- *Outcomes* of every optimization session: how many produced a merged PR, an open PR
  (awaiting review), are still in flight, or ended without a PR (Devin found nothing
  worth changing — a valid result).
- *Success rate*: share of finished sessions that produced a PR.
- *Coverage*: how much of the dependency set has been optimized at least once.
- *Throughput*: sessions started and PRs produced over time, from the run history.
- *Rework*: follow-up commits needed after Devin's first PR commit.
- *Cost*: ACUs consumed.

This module is pure (no I/O); the CLI and runner feed it data and render the result.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from .state import SessionEntry

# Devin session statuses that mean the session is still doing (or could resume) work.
_ACTIVE_STATUSES = {"running", "working", "resumed", "starting", "queued"}
# Statuses that mean a human needs to act for the session to make progress.
_BLOCKED_STATUSES = {"blocked"}


class Outcome(StrEnum):
    """Bucket a session falls into, derived from its session + PR state."""

    PR_MERGED = "pr_merged"  # improvement landed
    PR_OPEN = "pr_open"  # improvement awaiting human review
    ACTIVE = "active"  # session still working
    BLOCKED = "blocked"  # session needs human input
    COMPLETED_NO_PR = "completed_no_pr"  # ended without a PR (nothing worth changing)
    UNKNOWN = "unknown"  # triggered but never synced


def classify(entry: SessionEntry) -> Outcome:
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
    return Outcome.COMPLETED_NO_PR


# Outcomes that represent a session that has come to rest (for success-rate math).
_TERMINAL = {Outcome.PR_MERGED, Outcome.PR_OPEN, Outcome.COMPLETED_NO_PR}
_PRODUCED_PR = {Outcome.PR_MERGED, Outcome.PR_OPEN}


@dataclass
class Coverage:
    """How much of the dependency set has been optimized at least once."""

    total: int
    optimized: int
    considered: int

    @property
    def pct_optimized(self) -> float:
        return round(100.0 * self.optimized / self.total, 1) if self.total else 0.0


def _display_name(entry: SessionEntry) -> str:
    if entry.chosen_name:
        return entry.chosen_name
    return "(pending choice)"


@dataclass
class Report:
    generated_at: str
    entries: list[SessionEntry]
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

    # -- rework signal (commits after Devin's first PR commit) -------------

    @property
    def _prs_with_commit_data(self) -> list[SessionEntry]:
        return [e for e in self.entries if e.followup_commits is not None]

    @property
    def prs_with_followups(self) -> int:
        return sum(1 for e in self._prs_with_commit_data if (e.followup_commits or 0) > 0)

    @property
    def total_followup_commits(self) -> int:
        return sum(e.followup_commits or 0 for e in self._prs_with_commit_data)

    @property
    def total_human_followup_commits(self) -> int:
        return sum(e.human_followup_commits or 0 for e in self._prs_with_commit_data)

    @property
    def pct_prs_needing_changes(self) -> float | None:
        n = len(self._prs_with_commit_data)
        if n == 0:
            return None
        return round(100.0 * self.prs_with_followups / n, 1)

    @property
    def avg_followup_commits(self) -> float | None:
        n = len(self._prs_with_commit_data)
        if n == 0:
            return None
        return round(self.total_followup_commits / n, 2)

    @property
    def history_totals(self) -> dict[str, int]:
        keys = ("checked", "shortlisted", "triggered", "errors")
        return {k: sum(int(r.get(k, 0)) for r in self.history) for k in keys}

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict:
        out = {
            "generated_at": self.generated_at,
            "totals": {
                "sessions": self.total,
                "active": self.active,
                "completed": self.completed,
                "prs_open": self.prs_open,
                "prs_merged": self.prs_merged,
                "success_rate_pct": self.success_rate,
                "acus_consumed": self.total_acus,
            },
            "by_outcome": {o.value: n for o, n in self.by_outcome.items()},
            "runs": {"count": len(self.history), **self.history_totals},
            "sessions": [
                {
                    "package": _display_name(e),
                    "ecosystem": e.chosen_ecosystem,
                    "outcome": classify(e).value,
                    "status": e.status,
                    "pr_url": e.pr_url,
                    "pr_state": e.pr_state,
                    "session_url": e.session_url,
                    "triggered_at": e.triggered_at,
                    "acus_consumed": e.acus_consumed,
                    "followup_commits": e.followup_commits,
                    "human_followup_commits": e.human_followup_commits,
                }
                for e in self.entries
            ],
        }
        out["rework"] = {
            "prs_with_commit_data": len(self._prs_with_commit_data),
            "prs_needing_changes": self.prs_with_followups,
            "pct_prs_needing_changes": self.pct_prs_needing_changes,
            "avg_followup_commits": self.avg_followup_commits,
            "total_followup_commits": self.total_followup_commits,
            "total_human_followup_commits": self.total_human_followup_commits,
        }
        if self.coverage is not None:
            out["coverage"] = {
                "total": self.coverage.total,
                "optimized": self.coverage.optimized,
                "considered": self.coverage.considered,
                "pct_optimized": self.coverage.pct_optimized,
            }
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def build_report(
    entries: list[SessionEntry],
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
    Outcome.COMPLETED_NO_PR: "ended, no change",
    Outcome.UNKNOWN: "unknown (not synced)",
}


def _fmt_pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v}%"


def render_text(report: Report) -> str:
    lines: list[str] = []
    lines.append(f"Dependency optimization report  (generated {report.generated_at})")
    lines.append("=" * 60)
    if report.coverage is not None:
        cov = report.coverage
        lines.append(
            f"Coverage: {cov.optimized}/{cov.total} deps optimized at least once "
            f"({cov.pct_optimized}%); {cov.considered} considered"
        )
    lines.append(
        f"Sessions: {report.total}  |  active: {report.active}  "
        f"|  completed: {report.completed}"
    )
    lines.append(
        f"PRs: {report.prs_open} open, {report.prs_merged} merged  "
        f"|  success rate: {_fmt_pct(report.success_rate)}  "
        f"|  ACUs: {report.total_acus}"
    )
    if report._prs_with_commit_data:
        lines.append(
            f"Rework: {_fmt_pct(report.pct_prs_needing_changes)} of PRs needed follow-up "
            f"commits (avg {report.avg_followup_commits}/PR, "
            f"{report.total_human_followup_commits} human)"
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
            f"Across {len(report.history)} run(s): shortlisted {h['shortlisted']}, "
            f"triggered {h['triggered']}, errors {h['errors']}"
        )
    lines.append("")
    lines.append("Sessions:")
    for e in report.entries:
        oc = _OUTCOME_LABEL[classify(e)]
        suffix = f"  {e.pr_url}" if e.pr_url else (f"  {e.session_url}" if e.session_url else "")
        lines.append(f"  {_display_name(e)}: {oc}{suffix}")
    return "\n".join(lines)


def render_markdown(report: Report) -> str:
    lines: list[str] = []
    lines.append("## Dependency optimization report")
    lines.append("")
    lines.append(f"_Generated {report.generated_at}_")
    lines.append("")
    if report.coverage is not None:
        cov = report.coverage
        lines.append(
            f"**Coverage:** {cov.optimized}/{cov.total} dependencies optimized at least "
            f"once (**{cov.pct_optimized}%**); {cov.considered} considered"
        )
        lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Optimization sessions | {report.total} |")
    lines.append(f"| Active sessions | {report.active} |")
    lines.append(f"| Completed | {report.completed} |")
    lines.append(f"| PRs open (awaiting review) | {report.prs_open} |")
    lines.append(f"| PRs merged | {report.prs_merged} |")
    lines.append(f"| Success rate (finished → PR) | {_fmt_pct(report.success_rate)} |")
    lines.append(f"| ACUs consumed | {report.total_acus} |")
    if report._prs_with_commit_data:
        lines.append(
            f"| PRs needing follow-up commits | {_fmt_pct(report.pct_prs_needing_changes)} |"
        )
        lines.append(f"| Avg follow-up commits / PR | {report.avg_followup_commits} |")
    if report.history:
        h = report.history_totals
        lines.append(f"| Runs recorded | {len(report.history)} |")
        lines.append(f"| Sessions triggered (all runs) | {h['triggered']} |")
    lines.append("")
    lines.append("### Sessions")
    lines.append("")
    lines.append("| Package | Outcome | Follow-up commits | Link |")
    lines.append("| --- | --- | --- | --- |")
    for e in report.entries:
        oc = _OUTCOME_LABEL[classify(e)]
        link = ""
        if e.pr_url:
            link = f"[PR]({e.pr_url})"
        elif e.session_url:
            link = f"[session]({e.session_url})"
        followups = "-" if e.followup_commits is None else str(e.followup_commits)
        lines.append(f"| `{_display_name(e)}` | {oc} | {followups} | {link} |")
    lines.append("")
    return "\n".join(lines)
