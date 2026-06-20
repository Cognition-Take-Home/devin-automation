"""Lightweight GitHub access for the *rework* metric.

After Devin opens a PR, how often does the branch need additional commits? That is a
strong "is this actually landable?" signal: a PR that merges with zero follow-up commits
needed little human correction, while many follow-ups suggest the upgrade was hard.

We read a PR's commit list and, treating the **first** commit as Devin's initial work,
count the *follow-up* commits (everything after it) and how many of those came from a
human (i.e. not the Devin bot).

Data is fetched with the authenticated ``gh`` CLI by default (available and authenticated
both locally and on GitHub Actions runners). The command runner is injectable for tests.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

# Logins treated as "Devin", so commits by these are not counted as human rework.
_BOT_LOGINS = {"devin-ai-integration[bot]", "devin-ai-integration", "bot_apk"}

_PR_URL_RE = re.compile(r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)")


class GitHubError(RuntimeError):
    pass


@dataclass
class CommitStats:
    total_commits: int
    # Commits after the first (Devin's initial PR commit) — i.e. iterations/rework.
    followup_commits: int
    # Of those follow-ups, how many came from a non-Devin (human) author.
    human_followup_commits: int


def parse_pr_url(url: str) -> tuple[str, str, int] | None:
    """Return ``(owner, repo, number)`` from a GitHub PR URL, or ``None``."""
    m = _PR_URL_RE.search(url or "")
    if not m:
        return None
    return m.group("owner"), m.group("repo"), int(m.group("number"))


def _gh_runner(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except FileNotFoundError as exc:
        raise GitHubError("gh CLI not found") from exc
    except subprocess.CalledProcessError as exc:
        raise GitHubError(f"gh failed: {exc.stderr.strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitHubError("gh timed out") from exc
    return result.stdout


class GitHubClient:
    def __init__(self, runner=None):
        # ``runner`` signature: (args: list[str]) -> str (raw stdout). Injectable for tests.
        self._runner = runner or _gh_runner

    def list_pr_commits(self, owner: str, repo: str, number: int) -> list[dict]:
        """Return commits for a PR as ``[{"login": str|None, "date": str}, ...]`` (oldest first)."""
        out = self._runner(
            ["api", f"repos/{owner}/{repo}/pulls/{number}/commits", "--paginate"]
        )
        raw = json.loads(out) if out.strip() else []
        commits = []
        for c in raw:
            author = c.get("author") or {}
            commit = c.get("commit") or {}
            commit_author = commit.get("author") or {}
            commits.append(
                {"login": author.get("login"), "date": commit_author.get("date")}
            )
        return commits

    def commit_stats(self, pr_url: str) -> CommitStats | None:
        parsed = parse_pr_url(pr_url)
        if parsed is None:
            return None
        owner, repo, number = parsed
        commits = self.list_pr_commits(owner, repo, number)
        return summarize_commits(commits)


def summarize_commits(commits: list[dict]) -> CommitStats:
    """Pure aggregation over a PR's commit list (oldest first)."""
    total = len(commits)
    followups = commits[1:] if total > 1 else []
    human = sum(1 for c in followups if (c.get("login") or "") not in _BOT_LOGINS)
    return CommitStats(
        total_commits=total,
        followup_commits=len(followups),
        human_followup_commits=human,
    )
