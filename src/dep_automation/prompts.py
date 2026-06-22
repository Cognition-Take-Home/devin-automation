"""Builds the Devin session prompt for a nightly *library usage optimization*.

The automation is not a version bumper. Each run hands Devin a small shortlist of
dependencies the repo already uses and asks it to pick the single best opportunity, deep
-dive how that library is used versus how it *should* be used (per its official docs),
and make small, safe improvements — never large rewrites, and never a forced change.
Crucially, Devin may conclude there is nothing worthwhile and open no PR.
"""

from __future__ import annotations

from .config import Config
from .models import Candidate

_REGISTRY_LABEL = {"pypi": "PyPI", "npm": "npm"}

# Devin marks its chosen package in the PR title with this prefix so the harness can
# resolve which candidate was actually optimized, e.g. ``opt(cryptography): ...``.
OPT_TITLE_PREFIX = "opt"


def _candidate_lines(candidates: list[Candidate]) -> str:
    lines = []
    for c in candidates:
        registry = _REGISTRY_LABEL.get(c.ecosystem.value, c.ecosystem.value)
        d = c.dependency
        lines.append(
            f"- `{d.name}` ({registry}, declared `{d.constraint}` in `{d.manifest}`) "
            f"— ~{c.usage} usage references in the repo"
        )
    return "\n".join(lines)


def build_optimization_prompt(candidates: list[Candidate], config: Config) -> str:
    pr_kind = "draft pull request" if config.create_draft_pr else "pull request"
    return f"""\
You are improving how the repository `{config.target_repo}` (base branch \
`{config.base_branch}`) *uses* the libraries it already depends on. This is NOT a \
version upgrade task — do not bump versions. The goal is better, more idiomatic, safer \
use of an existing dependency.

## Candidate libraries (pick exactly ONE)
{_candidate_lines(candidates)}

Choose the single library where you can find the most genuine, low-risk improvement. If \
two are close, prefer the more heavily used one.

## What to do
1. **Study how the repo uses the library you chose.** Find the call sites and patterns \
in the codebase.
2. **Study how the library is meant to be used** at its currently-installed version: \
read the official documentation, API reference, and relevant guides.
3. **Find small, safe improvements** where the repo's usage diverges from current best \
practice — e.g. deprecated APIs still in use, redundant workarounds the library now \
makes unnecessary, simpler/more idiomatic calls, easy correctness or performance wins, \
recommended options not being set.
4. **Make only those small, clearly-beneficial changes.** Keep the diff focused and easy \
to review.

## Hard rules
- **No large or risky rewrites.** If a worthwhile improvement would require a big or \
risky change, do NOT make it — note it in the PR description under "Suggested \
follow-ups" instead.
- **It is OK to find nothing.** If there is no clearly-beneficial, low-risk improvement, \
do NOT open a PR. Report what you reviewed and why nothing was worth changing.
- **Do not bump the dependency's version** or change unrelated dependencies/code.
- **Do not weaken** tests, type checks, lint, or CI. Run the repo's lint/type/test \
suites (and pre-commit hooks) before opening a PR.
- Respect the repo's contribution guidelines (AGENTS.md / CONTRIBUTING / pre-commit).

## Deliverable (only if you found a worthwhile improvement)
Open a {pr_kind} against `{config.base_branch}`. **Title it** \
`{OPT_TITLE_PREFIX}(<package-name>): <short summary>` using the exact package name you \
chose (this lets the automation track which library was optimized). The description must \
explain: which library and call sites you changed, what each change improves (with links \
to the docs that justify it), and a "Suggested follow-ups" section for anything you \
intentionally did not do.
"""


def build_optimization_title() -> str:
    return "deps: nightly library usage optimization"
