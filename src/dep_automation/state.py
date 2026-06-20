"""Persistent de-duplication and outcome state.

Records the latest version we have already started a Devin session for, keyed by
``ecosystem:name``. This prevents the automation from re-triggering a session for the
same release on every poll, and also stores the *outcome* of each session (status, any
PR, ACUs consumed) so the reporting layer can answer "is this working?". The file is
committed back to the repo by the workflow so state survives across runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import Ecosystem


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class StateEntry:
    """One tracked upgrade: the trigger info plus the latest synced outcome."""

    name: str
    ecosystem: str
    version: str
    update_kind: str | None = None
    session_id: str | None = None
    session_url: str | None = None
    triggered_at: str | None = None
    # synced outcome fields
    status: str | None = None
    status_detail: str | None = None
    pr_url: str | None = None
    pr_state: str | None = None
    acus_consumed: float | None = None
    last_synced: str | None = None

    @classmethod
    def from_dict(cls, key: str, raw: dict) -> StateEntry:
        # Backfill name/ecosystem from the key for entries written by older versions.
        eco, _, name = key.partition(":")
        return cls(
            name=raw.get("name", name),
            ecosystem=raw.get("ecosystem", eco),
            version=raw.get("version", ""),
            update_kind=raw.get("update_kind"),
            session_id=raw.get("session_id"),
            session_url=raw.get("session_url"),
            triggered_at=raw.get("triggered_at"),
            status=raw.get("status"),
            status_detail=raw.get("status_detail"),
            pr_url=raw.get("pr_url"),
            pr_state=raw.get("pr_state"),
            acus_consumed=raw.get("acus_consumed"),
            last_synced=raw.get("last_synced"),
        )

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class State:
    def __init__(self, path: Path, data: dict[str, dict] | None = None):
        self._path = path
        self._data: dict[str, dict] = data or {}

    @staticmethod
    def _key(ecosystem: Ecosystem | str, name: str) -> str:
        eco = ecosystem.value if isinstance(ecosystem, Ecosystem) else ecosystem
        return f"{eco}:{name.lower()}"

    @classmethod
    def load(cls, path: str | Path) -> State:
        p = Path(path)
        if not p.exists():
            return cls(p, {})
        try:
            return cls(p, json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError):
            return cls(p, {})

    def already_triggered(self, ecosystem: Ecosystem, name: str, version: str) -> bool:
        entry = self._data.get(self._key(ecosystem, name))
        return bool(entry and entry.get("version") == version)

    def record(
        self,
        ecosystem: Ecosystem,
        name: str,
        version: str,
        session_id: str | None = None,
        session_url: str | None = None,
        update_kind: str | None = None,
    ) -> None:
        self._data[self._key(ecosystem, name)] = {
            "name": name,
            "ecosystem": ecosystem.value,
            "version": version,
            "update_kind": update_kind,
            "session_id": session_id,
            "session_url": session_url,
            "triggered_at": _now(),
        }

    def update_status(
        self,
        ecosystem: Ecosystem | str,
        name: str,
        *,
        status: str | None = None,
        status_detail: str | None = None,
        pr_url: str | None = None,
        pr_state: str | None = None,
        acus_consumed: float | None = None,
    ) -> None:
        entry = self._data.get(self._key(ecosystem, name))
        if entry is None:
            return
        entry.update(
            status=status,
            status_detail=status_detail,
            pr_url=pr_url,
            pr_state=pr_state,
            acus_consumed=acus_consumed,
            last_synced=_now(),
        )

    def entries(self) -> list[StateEntry]:
        return [StateEntry.from_dict(k, v) for k, v in sorted(self._data.items())]

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, sort_keys=True) + "\n")
