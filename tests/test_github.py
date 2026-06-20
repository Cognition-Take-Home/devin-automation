import json

from dep_automation.github import (
    GitHubClient,
    parse_pr_url,
    summarize_commits,
)


def test_parse_pr_url():
    assert parse_pr_url("https://github.com/o/r/pull/57") == ("o", "r", 57)
    assert parse_pr_url("http://github.com/Cog-Take/superset/pull/9/files") == (
        "Cog-Take",
        "superset",
        9,
    )
    assert parse_pr_url("not a url") is None
    assert parse_pr_url("") is None


def test_summarize_commits_counts_followups_and_humans():
    commits = [
        {"login": "devin-ai-integration[bot]", "date": "2026-01-01T00:00:00Z"},  # initial
        {"login": "devin-ai-integration[bot]", "date": "2026-01-02T00:00:00Z"},  # devin follow-up
        {"login": "alice", "date": "2026-01-03T00:00:00Z"},  # human follow-up
    ]
    stats = summarize_commits(commits)
    assert stats.total_commits == 3
    assert stats.followup_commits == 2
    assert stats.human_followup_commits == 1


def test_summarize_commits_single_commit_is_no_rework():
    stats = summarize_commits([{"login": "devin-ai-integration[bot]", "date": "x"}])
    assert stats.total_commits == 1
    assert stats.followup_commits == 0
    assert stats.human_followup_commits == 0


def test_summarize_commits_empty():
    stats = summarize_commits([])
    assert stats.total_commits == 0
    assert stats.followup_commits == 0


def test_client_commit_stats_uses_runner():
    payload = [
        {"author": {"login": "devin-ai-integration[bot]"}, "commit": {"author": {"date": "d1"}}},
        {"author": {"login": "bob"}, "commit": {"author": {"date": "d2"}}},
    ]

    captured = {}

    def runner(args):
        captured["args"] = args
        return json.dumps(payload)

    client = GitHubClient(runner=runner)
    stats = client.commit_stats("https://github.com/o/r/pull/12")
    assert captured["args"][:2] == ["api", "repos/o/r/pulls/12/commits"]
    assert stats.total_commits == 2
    assert stats.followup_commits == 1
    assert stats.human_followup_commits == 1


def test_client_commit_stats_bad_url_returns_none():
    client = GitHubClient(runner=lambda args: "[]")
    assert client.commit_stats("nope") is None
