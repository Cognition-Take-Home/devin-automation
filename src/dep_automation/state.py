"""Persistent de-duplication state.

Records the latest version we have already started a Devin session for, keyed by
``ecosystem:name``. This prevents the automation from re-triggering a session for the
same release on every poll. The file is committed back to the repo by the workflow so
state survives across runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import Ecosystem


@dataclass
class StateEntry:
    version: str
    session_id: str | None
    session_url: str | None
    triggered_at: str


class State:
    def __init__(self, path: Path, data: dict[str, dict] | None = None):
        self._path = path
        self._data: dict[str, dict] = data or {}

    @staticmethod
    def _key(ecosystem: Ecosystem, name: str) -> str:
        return f"{ecosystem.value}:{name.lower()}"

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
    ) -> None:
        self._data[self._key(ecosystem, name)] = {
            "version": version,
            "session_id": session_id,
            "session_url": session_url,
            "triggered_at": datetime.now(UTC).isoformat(),
        }

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, sort_keys=True) + "\n")
