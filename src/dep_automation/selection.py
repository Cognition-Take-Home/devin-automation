"""Pick the nightly shortlist of optimization candidates.

The harness narrows the full dependency list to a small shortlist (Devin then chooses
which one to actually optimize). Ranking is: most-used in the repo first, excluding any
dependency considered within the cooldown window so the automation rotates across the
whole library set over time rather than re-poking the same few. If the cooldown would
exclude everything, it relaxes (rotation has wrapped around).
"""

from __future__ import annotations

from .models import Candidate, Dependency


def _key(dep: Dependency) -> tuple[str, str]:
    return (dep.ecosystem.value, dep.name.lower())


def select_candidates(
    deps: list[Dependency],
    usage: dict[tuple[str, str], int],
    recently_considered: set[tuple[str, str]],
    *,
    shortlist_size: int = 5,
) -> list[Candidate]:
    """Return up to ``shortlist_size`` candidates, most-used first, skipping cooldown."""
    eligible = [d for d in deps if _key(d) not in recently_considered]
    if not eligible:
        eligible = list(deps)

    def rank(dep: Dependency) -> tuple[int, str]:
        # Higher usage first (negate), then alphabetical for a stable tie-break.
        return (-usage.get(_key(dep), 0), dep.name.lower())

    chosen = sorted(eligible, key=rank)[:shortlist_size]
    return [Candidate(dependency=d, usage=usage.get(_key(d), 0)) for d in chosen]
