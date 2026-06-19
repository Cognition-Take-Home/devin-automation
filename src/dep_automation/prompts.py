"""Builds the Devin session prompt for a research-led dependency upgrade.

The prompt is the product's core: it instructs Devin to *understand* what changed
between the current and latest version and to adopt improvements judiciously, rather
than blindly bumping a number and hoping CI is green. Crucially, it tells Devin **not
to force** changes - breaking or risky adoptions should be surfaced, not pushed.
"""

from __future__ import annotations

from .config import Config
from .models import OutdatedDependency

_REGISTRY_LABEL = {"pypi": "PyPI", "npm": "npm"}


def build_prompt(dep: OutdatedDependency, config: Config) -> str:
    d = dep.dependency
    registry = _REGISTRY_LABEL.get(d.ecosystem.value, d.ecosystem.value)
    current = d.current_version or d.constraint or "unknown"
    pr_kind = "draft pull request" if config.create_draft_pr else "pull request"

    return f"""\
You are performing a careful, research-led dependency upgrade for the repository \
`{config.target_repo}` (base branch `{config.base_branch}`).

## Dependency
- Package: `{d.name}` ({registry})
- Declared in: `{d.manifest}`
- Current constraint: `{d.constraint}` (currently resolves around `{current}`)
- Latest published version: `{dep.latest_version}`
- Update size: {dep.update_kind.value}

## What to do
1. **Research first - do not just bump the version.** Find the authoritative \
documentation for every release between `{current}` and `{dep.latest_version}`: the \
project's CHANGELOG / release notes, migration guides, and relevant docs. Summarize the \
notable changes - new APIs, deprecations, removals, behavioral changes, performance \
improvements, and security fixes.
2. **Update the dependency** in `{d.manifest}` to adopt `{dep.latest_version}` (adjust \
the version constraint appropriately and update any lock file the repo uses).
3. **Thoughtfully adopt improvements.** Where the new version unlocks better APIs, \
simpler patterns, performance wins, or lets us remove workarounds/shims that existed \
only for the old version, update the codebase to take advantage of them. Prefer changes \
that are clearly beneficial and low-risk.
4. **Fix what the upgrade breaks** - resolve deprecations and required migrations so the \
build, type checks, lint, and tests pass.

## Hard rules - do NOT force changes
- **Do not force risky, speculative, or large refactors.** If adopting a new capability \
would require a substantial or risky change, **do not make it** - instead document it \
in the PR description under a "Deferred / suggested follow-ups" section with enough \
context for a maintainer to decide.
- **Do not relax or weaken** existing tests, type checks, lint rules, or CI just to make \
things pass. If the upgrade genuinely cannot be completed safely, stop and explain why \
in the PR rather than forcing it through.
- **Do not touch unrelated dependencies or code.** Keep this PR scoped to `{d.name}` and \
the changes its upgrade directly motivates.
- Respect the repository's own contribution guidelines (AGENTS.md / CONTRIBUTING / \
pre-commit hooks). Run the repo's lint, type, and test suites locally before opening the PR.

## Deliverable
Open a {pr_kind} against `{config.base_branch}` titled \
`chore(deps): upgrade {d.name} to {dep.latest_version}`. The PR description must include:
- A short summary of what changed between `{current}` and `{dep.latest_version}` (with \
links to the changelog/release notes you used).
- Exactly which improvements you adopted and why.
- A "Deferred / suggested follow-ups" section for anything you intentionally did not \
force, including breaking changes you chose not to make.
- Confirmation of which checks you ran and their results.

If the upgrade turns out to be infeasible or clearly inadvisable, do not open a PR that \
forces it - instead report your findings and recommendation.
"""


def build_title(dep: OutdatedDependency) -> str:
    return f"deps: research-led upgrade of {dep.name} -> {dep.latest_version}"
