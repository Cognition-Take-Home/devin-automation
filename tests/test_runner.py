from pathlib import Path

from dep_automation.config import Config, ManifestSpec
from dep_automation.devin import CreatedSession, SessionStatus
from dep_automation.github import CommitStats
from dep_automation.runner import Runner
from dep_automation.state import State

FIX = Path(__file__).parent / "fixtures"

# Fake usage counts keyed by lowercased dependency name. Higher = more used.
USAGE = {
    "pandas": 500,
    "click": 400,
    "gunicorn": 300,
    "celery": 200,
    "colorama": 100,
    "react": 90,
    "typescript": 80,
    "eslint": 70,
    "@braintree/sanitize-url": 60,
    "@deck.gl/aggregation-layers": 50,
}


class FakeUsage:
    def __init__(self, table):
        self.table = table

    def count(self, dep):
        return self.table.get(dep.name.lower(), 0)

    def counts(self, deps):
        return {(d.ecosystem.value, d.name.lower()): self.count(d) for d in deps}


class FakeDevin:
    def __init__(self, statuses=None):
        self.calls = []
        self.statuses = statuses or {}

    def create_session(self, prompt, *, title=None, tags=None, idempotent=True, max_acu_limit=None):
        self.calls.append({"prompt": prompt, "title": title, "tags": tags})
        idx = len(self.calls)
        return CreatedSession(
            session_id=f"devin-{idx}", url=f"https://app.devin.ai/sessions/{idx}"
        )

    def get_session(self, session_id):
        return self.statuses.get(session_id, SessionStatus(session_id=session_id))


class FakeGitHub:
    def __init__(self, title=None, stats=None):
        self.title = title
        self.stats = stats or CommitStats(
            total_commits=2, followup_commits=1, human_followup_commits=1
        )
        self.title_calls = []
        self.stats_calls = []

    def pr_title(self, pr_url):
        self.title_calls.append(pr_url)
        return self.title

    def commit_stats(self, pr_url):
        self.stats_calls.append(pr_url)
        return self.stats


def make_config(tmp_path, **overrides) -> Config:
    cfg = Config(
        target_repo="acme/target",
        target_repo_path=str(FIX),
        base_branch="master",
        manifests=[
            ManifestSpec(path="sample_pyproject.toml"),
            ManifestSpec(path="sample_package.json"),
        ],
        state_path=str(tmp_path / "state.json"),
        history_path=str(tmp_path / "history.jsonl"),
        shortlist_size=3,
        ignore=[],
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def make_runner(tmp_path, devin=None, github=None, **cfg_overrides):
    cfg = make_config(tmp_path, **cfg_overrides)
    devin = devin or FakeDevin()
    runner = Runner(
        cfg,
        devin=devin,
        state=State.load(cfg.state_path),
        github=github or FakeGitHub(),
        usage=FakeUsage(USAGE),
    )
    return runner, devin


def test_shortlist_ranks_by_usage(tmp_path):
    runner, _ = make_runner(tmp_path)
    picked = [c.name for c in runner.shortlist()]
    assert picked == ["pandas", "click", "gunicorn"]


def test_optimize_triggers_one_session(tmp_path):
    runner, devin = make_runner(tmp_path)
    result = runner.optimize()
    assert result.triggered is True
    assert len(devin.calls) == 1
    # the prompt is a usage-optimization prompt, not a version bump
    prompt = devin.calls[0]["prompt"]
    assert "NOT a version upgrade" in prompt
    assert "It is OK to find nothing" in prompt
    assert len(result.candidates) == 3


def test_optimize_dry_run_creates_no_session(tmp_path):
    runner, devin = make_runner(tmp_path)
    result = runner.optimize(dry_run=True)
    assert result.triggered is False
    assert devin.calls == []
    assert result.skipped_reason == "dry-run"


def test_cooldown_rotates_candidates(tmp_path):
    runner, _ = make_runner(tmp_path)
    first = {c.name for c in runner.shortlist()}
    runner.optimize()  # records the shortlist as considered

    runner2, _ = make_runner(tmp_path)  # reloads persisted state
    second = {c.name for c in runner2.shortlist()}
    assert first.isdisjoint(second)  # cooldown excludes the just-considered set


def test_cooldown_zero_disables_rotation(tmp_path):
    runner, _ = make_runner(tmp_path, cooldown_days=0)
    runner.optimize()
    runner2, _ = make_runner(tmp_path, cooldown_days=0)
    # with no cooldown the most-used set is offered again
    assert [c.name for c in runner2.shortlist()] == ["pandas", "click", "gunicorn"]


def test_optimize_appends_history(tmp_path):
    runner, _ = make_runner(tmp_path)
    runner.optimize()
    history = runner.load_history()
    assert len(history) == 1
    assert history[0]["triggered"] == 1
    assert history[0]["shortlisted"] == 3


def test_sync_resolves_choice_and_commits(tmp_path):
    devin = FakeDevin(
        statuses={
            "devin-1": SessionStatus(
                session_id="devin-1",
                status="finished",
                pr_url="https://github.com/acme/target/pull/9",
                pr_state="open",
                acus_consumed=3.5,
            )
        }
    )
    github = FakeGitHub(title="opt(pandas): use pyarrow dtypes")
    runner, _ = make_runner(tmp_path, devin=devin, github=github)
    runner.optimize()

    synced = runner.sync_statuses()
    assert synced == 1

    entry = runner.state.sessions()[0]
    assert entry.pr_url.endswith("/pull/9")
    assert entry.acus_consumed == 3.5
    assert entry.chosen_name == "pandas"
    assert entry.chosen_ecosystem == "pypi"
    assert entry.followup_commits == 1
    # the chosen dep is now counted as optimized for coverage
    assert runner.state.optimized_count() == 1


def test_sync_without_pr_does_not_resolve_choice(tmp_path):
    devin = FakeDevin(
        statuses={"devin-1": SessionStatus(session_id="devin-1", status="finished")}
    )
    github = FakeGitHub(title="opt(pandas): x")
    runner, _ = make_runner(tmp_path, devin=devin, github=github)
    runner.optimize()
    runner.sync_statuses()
    assert github.title_calls == []  # no PR -> no title lookup
    assert runner.state.optimized_count() == 0


def test_build_report_with_coverage(tmp_path):
    runner, _ = make_runner(tmp_path)
    runner.optimize()
    report = runner.build_report(coverage=True)
    assert report.total == 1
    assert report.coverage is not None
    assert report.coverage.total == 10  # all deps in the fixtures
    assert report.coverage.considered == 3


def test_ignore_filter(tmp_path):
    runner, _ = make_runner(tmp_path, ignore=["pandas"])
    assert "pandas" not in {c.name for c in runner.shortlist()}


def test_only_filter(tmp_path):
    runner, _ = make_runner(tmp_path, only=["gunicorn"])
    assert [c.name for c in runner.shortlist()] == ["gunicorn"]
