"""Measure how heavily the target repo uses each dependency.

This is a cheap, harness-side heuristic used only to *rank* candidates before handing a
shortlist to Devin — it does not need to be exact. We count, with ripgrep, how often a
package's import name appears across the repo's source. ripgrep honours .gitignore, so
vendored trees like ``node_modules`` are skipped automatically. Matching is anchored so
short names (e.g. ``ol``) don't get inflated by substring hits inside unrelated words:

- **npm**: count import specifiers that start with the package name, i.e. the name
  immediately inside a quote and followed by a quote or ``/`` (``'ol'`` / ``"ol/foo"``).
- **PyPI**: count whole-word occurrences of the import module name(s) (distribution
  names are normalised by swapping separators, which covers the common cases).

The command runner is injectable for tests.
"""

from __future__ import annotations

import re
import subprocess

from .models import Dependency, Ecosystem


def search_patterns(dep: Dependency) -> list[str]:
    """Regex pattern(s) approximating how the package is referenced in source."""
    if dep.ecosystem == Ecosystem.NPM:
        # Import specifier beginning with the package name: '<name>' or "<name>/...".
        return [rf"""['"]{re.escape(dep.name)}(?:['"/])"""]
    n = dep.name.lower()
    variants = sorted({n, n.replace("-", "_"), n.replace("-", "."), n.replace(".", "_")})
    alternation = "|".join(re.escape(v) for v in variants)
    return [rf"\b(?:{alternation})\b"]


def _rg_runner(patterns: list[str], paths: list[str], cwd: str) -> str:
    """Default runner: ``rg --count-matches`` over the paths, returning ``path:count`` lines."""
    args = ["rg", "--count-matches", "--no-messages"]
    for pat in patterns:
        args += ["-e", pat]
    args += ["--", *paths]
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
    # rg exits 1 when there are no matches; that is not an error for us.
    return result.stdout


class UsageScanner:
    def __init__(self, config, runner=None):
        self._repo = config.target_repo_path
        self._config = config
        # runner signature: (patterns, paths, cwd) -> raw rg stdout. Injectable for tests.
        self._runner = runner or _rg_runner

    def count(self, dep: Dependency) -> int:
        patterns = search_patterns(dep)
        paths = self._config.usage_paths_for(dep.ecosystem)
        out = self._runner(patterns, paths, self._repo)
        total = 0
        for line in out.splitlines():
            _, _, num = line.rpartition(":")
            num = num.strip()
            if num.isdigit():
                total += int(num)
        return total

    def counts(self, deps: list[Dependency]) -> dict[tuple[str, str], int]:
        """Map ``(ecosystem, name_lower)`` -> usage count for each dependency."""
        return {(d.ecosystem.value, d.name.lower()): self.count(d) for d in deps}
