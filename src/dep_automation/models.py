"""Core data structures shared across the automation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Ecosystem(StrEnum):
    """Package ecosystem a dependency belongs to."""

    PYPI = "pypi"
    NPM = "npm"


class UpdateKind(StrEnum):
    """Semantic size of an available update."""

    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Dependency:
    """A single top-level dependency declared in a manifest."""

    name: str
    ecosystem: Ecosystem
    constraint: str
    manifest: str
    # The representative current version expressed by the constraint (anchor of a
    # caret/tilde range, a pin, or the highest lower bound). May be ``None`` when the
    # constraint has no concrete version (e.g. an unbounded ``*``).
    current_version: str | None = None


@dataclass(frozen=True)
class OutdatedDependency:
    """A dependency whose latest published version warrants attention."""

    dependency: Dependency
    latest_version: str
    update_kind: UpdateKind
    # ``True`` when the latest version is *not* permitted by the current constraint and
    # therefore requires a manifest edit (the high-value case for a Devin upgrade).
    requires_manifest_change: bool

    @property
    def name(self) -> str:
        return self.dependency.name

    @property
    def ecosystem(self) -> Ecosystem:
        return self.dependency.ecosystem


@dataclass
class TriggerResult:
    """Outcome of attempting to start a Devin session for one dependency."""

    dependency: OutdatedDependency
    triggered: bool
    skipped_reason: str | None = None
    session_id: str | None = None
    session_url: str | None = None


@dataclass
class RunReport:
    """Summary of a single automation run."""

    checked: int = 0
    outdated: list[OutdatedDependency] = field(default_factory=list)
    results: list[TriggerResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def triggered(self) -> list[TriggerResult]:
        return [r for r in self.results if r.triggered]
