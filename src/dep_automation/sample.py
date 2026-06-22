"""Synthetic sample data for demoing the dashboard.

The dashboard's "Use sample data" toggle calls :func:`build_sample_report` to render a
fully-populated view (KPI cards, outcomes chart, throughput chart, sessions table) without
needing real run history or live API access. Nothing here is persisted — it only ever
produces in-memory objects the reporting layer already understands.

The numbers are illustrative of an Apache Superset target repo: a spread of optimization
outcomes across both the PyPI and npm ecosystems, a few runs of throughput, and a coverage
snapshot against a large dependency set.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .metrics import Coverage, Report, build_report
from .state import SessionEntry

# (package, ecosystem, status, pr_state, pr?, acus, total_commits, followup, human_followup)
# pr_state/pr drive the outcome bucket via metrics.classify:
#   pr_state="merged" -> merged; pr_url set -> open; blocked/running -> active; else no-PR.
_SESSIONS: list[dict] = [
    {
        "package": "sqlalchemy", "ecosystem": "pypi", "status": "finished",
        "pr_state": "merged", "pr": True, "acus": 8.4,
        "total": 5, "followup": 1, "human": 0,
    },
    {
        "package": "pandas", "ecosystem": "pypi", "status": "finished",
        "pr_state": "merged", "pr": True, "acus": 6.1,
        "total": 3, "followup": 0, "human": 0,
    },
    {
        "package": "celery", "ecosystem": "pypi", "status": "finished",
        "pr_state": "merged", "pr": True, "acus": 11.7,
        "total": 7, "followup": 3, "human": 2,
    },
    {
        "package": "marshmallow", "ecosystem": "pypi", "status": "finished",
        "pr_state": "open", "pr": True, "acus": 5.5,
        "total": 2, "followup": 0, "human": 0,
    },
    {
        "package": "cryptography", "ecosystem": "pypi", "status": "finished",
        "pr_state": "open", "pr": True, "acus": 9.2,
        "total": 4, "followup": 2, "human": 1,
    },
    {
        "package": "redis", "ecosystem": "pypi", "status": "finished",
        "pr_state": None, "pr": False, "acus": 3.8,
        "total": None, "followup": None, "human": None,
    },
    {
        "package": "react", "ecosystem": "npm", "status": "finished",
        "pr_state": "merged", "pr": True, "acus": 10.3,
        "total": 6, "followup": 2, "human": 1,
    },
    {
        "package": "lodash", "ecosystem": "npm", "status": "finished",
        "pr_state": "open", "pr": True, "acus": 4.6,
        "total": 2, "followup": 1, "human": 0,
    },
    {
        "package": "d3", "ecosystem": "npm", "status": "finished",
        "pr_state": None, "pr": False, "acus": 2.9,
        "total": None, "followup": None, "human": None,
    },
    {
        "package": "antd", "ecosystem": "npm", "status": "running",
        "pr_state": None, "pr": False, "acus": 1.4,
        "total": None, "followup": None, "human": None,
    },
    {
        "package": "moment", "ecosystem": "npm", "status": "blocked",
        "pr_state": None, "pr": False, "acus": 2.0,
        "total": None, "followup": None, "human": None,
    },
]

# Per-run throughput: checked / shortlisted / triggered / errors.
_HISTORY = [
    {"checked": 312, "shortlisted": 5, "triggered": 1, "errors": 0},
    {"checked": 314, "shortlisted": 5, "triggered": 1, "errors": 0},
    {"checked": 315, "shortlisted": 5, "triggered": 1, "errors": 1},
    {"checked": 315, "shortlisted": 5, "triggered": 1, "errors": 0},
    {"checked": 316, "shortlisted": 5, "triggered": 1, "errors": 0},
]

_COVERAGE = Coverage(total=316, optimized=9, considered=24)


def sample_sessions(now: datetime | None = None) -> list[SessionEntry]:
    """Synthetic :class:`SessionEntry` records, newest first."""
    now = now or datetime.now(UTC)
    entries: list[SessionEntry] = []
    for i, s in enumerate(_SESSIONS):
        triggered = now - timedelta(days=len(_SESSIONS) - i, hours=3)
        slug = s["package"].replace("/", "-")
        pr_url = (
            f"https://github.com/Cognition-Take-Home/superset/pull/{4200 + i}"
            if s["pr"]
            else None
        )
        entries.append(
            SessionEntry(
                session_id=f"sample-{i:02d}-{slug}",
                session_url=f"https://app.devin.ai/sessions/sample{i:02d}",
                triggered_at=triggered.isoformat(),
                candidates=[f"{s['ecosystem']}:{s['package']}"],
                chosen_name=s["package"],
                chosen_ecosystem=s["ecosystem"],
                status=s["status"],
                pr_url=pr_url,
                pr_state=s["pr_state"],
                acus_consumed=s["acus"],
                last_synced=now.isoformat(),
                total_commits=s["total"],
                followup_commits=s["followup"],
                human_followup_commits=s["human"],
            )
        )
    return entries


def sample_history(now: datetime | None = None) -> list[dict]:
    """Synthetic run-history records with timestamps, oldest first."""
    now = now or datetime.now(UTC)
    n = len(_HISTORY)
    return [
        {"timestamp": (now - timedelta(days=n - i)).isoformat(), **row}
        for i, row in enumerate(_HISTORY)
    ]


def build_sample_report(*, coverage: bool = True, now: datetime | None = None) -> Report:
    """A fully-populated :class:`Report` built entirely from synthetic data."""
    now = now or datetime.now(UTC)
    return build_report(
        sample_sessions(now),
        coverage=_COVERAGE if coverage else None,
        history=sample_history(now),
        now=now,
    )
