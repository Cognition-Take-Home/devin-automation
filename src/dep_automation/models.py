"""Core data structures shared across the automation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Ecosystem(StrEnum):
    """Package ecosystem a dependency belongs to."""

    PYPI = "pypi"
    NPM = "npm"


@dataclass(frozen=True)
class Dependency:
    """A single top-level dependency declared in a manifest."""

    name: str
    ecosystem: Ecosystem
    constraint: str
    manifest: str


@dataclass(frozen=True)
class Candidate:
    """A dependency considered for optimization, with how heavily the repo uses it."""

    dependency: Dependency
    usage: int

    @property
    def name(self) -> str:
        return self.dependency.name

    @property
    def ecosystem(self) -> Ecosystem:
        return self.dependency.ecosystem


@dataclass
class OptimizeResult:
    """Outcome of a single nightly optimization run."""

    candidates: list[Candidate] = field(default_factory=list)
    triggered: bool = False
    session_id: str | None = None
    session_url: str | None = None
    skipped_reason: str | None = None
    errors: list[str] = field(default_factory=list)
