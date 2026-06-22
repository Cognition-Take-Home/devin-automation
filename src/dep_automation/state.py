"""Persistent state for the usage-optimization automation.

Two things are tracked, in one JSON file committed back by the workflow so it survives
across runs:

- ``sessions`` — every optimization session the automation started, keyed by session id,
  with the candidate shortlist, the package Devin ultimately chose (resolved from the PR
  title on sync), and the synced outcome (status, PR, ACUs, follow-up commits). This is
  what the reporting layer aggregates.
- ``deps`` — per-dependency bookkeeping: when it was last *considered* (shortlisted) and
  last *optimized* (chosen + produced a PR). ``considered`` drives the cooldown/rotation
  in selection; ``optimized`` drives coverage ("how much of the library set have we
  improved at least once?").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import Dependency, Ecosystem


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@dataclass
class SessionEntry:
    """One optimization session: the shortlist, the chosen package, and its outcome."""

    session_id: str
    session_url: str | None = None
    triggered_at: str | None = None
    candidates: list[str] | None = None  # "ecosystem:name" keys shown to Devin
    # The package Devin actually optimized, resolved from the PR title on sync.
    chosen_name: str | None = None
    chosen_ecosystem: str | None = None
    # synced outcome fields
    status: str | None = None
    status_detail: str | None = None
    pr_url: str | None = None
    pr_state: str | None = None
    acus_consumed: float | None = None
    last_synced: str | None = None
    # rework signal: commits on the PR branch after Devin's initial commit
    total_commits: int | None = None
    followup_commits: int | None = None
    human_followup_commits: int | None = None

    @classmethod
    def from_dict(cls, session_id: str, raw: dict) -> SessionEntry:
        return cls(
            session_id=raw.get("session_id", session_id),
            session_url=raw.get("session_url"),
            triggered_at=raw.get("triggered_at"),
            candidates=raw.get("candidates"),
            chosen_name=raw.get("chosen_name"),
            chosen_ecosystem=raw.get("chosen_ecosystem"),
            status=raw.get("status"),
            status_detail=raw.get("status_detail"),
            pr_url=raw.get("pr_url"),
            pr_state=raw.get("pr_state"),
            acus_consumed=raw.get("acus_consumed"),
            last_synced=raw.get("last_synced"),
            total_commits=raw.get("total_commits"),
            followup_commits=raw.get("followup_commits"),
            human_followup_commits=raw.get("human_followup_commits"),
        )


def _key(ecosystem: Ecosystem | str, name: str) -> str:
    eco = ecosystem.value if isinstance(ecosystem, Ecosystem) else ecosystem
    return f"{eco}:{name.lower()}"


class State:
    def __init__(self, path: Path, data: dict | None = None):
        self._path = path
        data = data or {}
        self._sessions: dict[str, dict] = data.get("sessions", {})
        self._deps: dict[str, dict] = data.get("deps", {})

    @classmethod
    def load(cls, path: str | Path) -> State:
        p = Path(path)
        if not p.exists():
            return cls(p, {})
        try:
            return cls(p, json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError):
            return cls(p, {})

    # -- recording ---------------------------------------------------------

    def record_session(
        self,
        session_id: str,
        session_url: str | None,
        candidates: list[Dependency],
    ) -> None:
        keys = [_key(d.ecosystem, d.name) for d in candidates]
        now = _iso(_now())
        self._sessions[session_id] = {
            "session_id": session_id,
            "session_url": session_url,
            "triggered_at": now,
            "candidates": keys,
        }
        for dep in candidates:
            rec = self._deps.setdefault(_key(dep.ecosystem, dep.name), {})
            rec["considered_at"] = now
            rec["considered_count"] = rec.get("considered_count", 0) + 1

    def recently_considered(self, cooldown_days: int, *, now: datetime | None = None) -> set[
        tuple[str, str]
    ]:
        """Keys considered within the cooldown window (excluded from new shortlists)."""
        if cooldown_days <= 0:
            return set()
        cutoff = (now or _now()) - timedelta(days=cooldown_days)
        out: set[tuple[str, str]] = set()
        for key, rec in self._deps.items():
            ts = rec.get("considered_at")
            if ts and _parse(ts) and _parse(ts) >= cutoff:
                eco, _, name = key.partition(":")
                out.add((eco, name))
        return out

    def mark_optimized(self, ecosystem: str, name: str) -> None:
        rec = self._deps.setdefault(_key(ecosystem, name), {})
        rec["optimized_at"] = _iso(_now())
        rec["optimized_count"] = rec.get("optimized_count", 0) + 1

    # -- sync --------------------------------------------------------------

    def update_session_status(
        self,
        session_id: str,
        *,
        status: str | None = None,
        status_detail: str | None = None,
        pr_url: str | None = None,
        pr_state: str | None = None,
        acus_consumed: float | None = None,
    ) -> None:
        entry = self._sessions.get(session_id)
        if entry is None:
            return
        entry.update(
            status=status,
            status_detail=status_detail,
            pr_url=pr_url,
            pr_state=pr_state,
            acus_consumed=acus_consumed,
            last_synced=_iso(_now()),
        )

    def set_session_choice(self, session_id: str, ecosystem: str, name: str) -> None:
        entry = self._sessions.get(session_id)
        if entry is None:
            return
        entry["chosen_ecosystem"] = ecosystem
        entry["chosen_name"] = name

    def update_session_commits(
        self,
        session_id: str,
        *,
        total_commits: int,
        followup_commits: int,
        human_followup_commits: int,
    ) -> None:
        entry = self._sessions.get(session_id)
        if entry is None:
            return
        entry.update(
            total_commits=total_commits,
            followup_commits=followup_commits,
            human_followup_commits=human_followup_commits,
        )

    # -- access ------------------------------------------------------------

    def sessions(self) -> list[SessionEntry]:
        return [
            SessionEntry.from_dict(k, v) for k, v in sorted(self._sessions.items())
        ]

    def optimized_count(self) -> int:
        return sum(1 for rec in self._deps.values() if rec.get("optimized_at"))

    def considered_count(self) -> int:
        return sum(1 for rec in self._deps.values() if rec.get("considered_at"))

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"sessions": self._sessions, "deps": self._deps}
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None
