from pathlib import Path

from dep_automation.config import Config, ManifestSpec
from dep_automation.devin import CreatedSession
from dep_automation.models import Ecosystem
from dep_automation.runner import Runner
from dep_automation.state import State

FIX = Path(__file__).parent / "fixtures"

# Latest versions returned by the fake registry, keyed by name.
LATEST = {
    # pyproject
    "celery": "5.9.9",  # in range (<6.0.0) -> not flagged under out-of-range
    "click": "8.4.0",  # equal -> not flagged
    "colorama": "0.4.6",  # no constraint -> in range
    "pandas": "2.5.0",  # > <2.4 cap -> out of range -> flagged (major-ish)
    "gunicorn": "26.1.0",  # > <26 cap -> out of range -> flagged
    # package.json
    "@braintree/sanitize-url": "7.9.0",  # within ^7.1.2 -> in range
    "@deck.gl/aggregation-layers": "9.5.0",  # outside ~9.2.5 -> flagged
    "react": "19.0.0",  # exact 18.3.1 -> flagged
    "typescript": "5.9.0",  # within ^5.4.0 -> in range
    "eslint": "9.5.0",  # outside <9.0.0 -> flagged
}


class FakeRegistry:
    def __init__(self, table):
        self.table = table

    def latest_version(self, ecosystem: Ecosystem, name: str) -> str:
        return self.table[name]


class FakeDevin:
    def __init__(self):
        self.calls = []

    def create_session(self, prompt, *, title=None, tags=None, idempotent=True, max_acu_limit=None):
        self.calls.append({"prompt": prompt, "title": title, "tags": tags})
        idx = len(self.calls)
        return CreatedSession(session_id=f"devin-{idx}", url=f"https://app.devin.ai/sessions/{idx}")


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
        ignore=[],
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def make_runner(tmp_path, **cfg_overrides):
    cfg = make_config(tmp_path, **cfg_overrides)
    devin = FakeDevin()
    runner = Runner(
        cfg,
        registry=FakeRegistry(LATEST),
        devin=devin,
        state=State.load(cfg.state_path),
    )
    return runner, devin


def test_find_outdated_out_of_range(tmp_path):
    runner, _ = make_runner(tmp_path)
    outdated = {od.name for od in runner.find_outdated()}
    assert outdated == {"pandas", "gunicorn", "@deck.gl/aggregation-layers", "react", "eslint"}


def test_any_newer_policy_flags_more(tmp_path):
    runner, _ = make_runner(tmp_path, trigger_policy="any-newer")
    outdated = {od.name for od in runner.find_outdated()}
    # celery (5.3.6 -> 5.9.9) and others now count as newer
    assert "celery" in outdated
    assert "@braintree/sanitize-url" in outdated


def test_ignore_filter(tmp_path):
    runner, _ = make_runner(tmp_path, ignore=["pandas", "react"])
    outdated = {od.name for od in runner.find_outdated()}
    assert "pandas" not in outdated
    assert "react" not in outdated


def test_only_filter(tmp_path):
    runner, _ = make_runner(tmp_path, only=["gunicorn"])
    outdated = {od.name for od in runner.find_outdated()}
    assert outdated == {"gunicorn"}


def test_run_triggers_sessions(tmp_path):
    runner, devin = make_runner(tmp_path)
    report = runner.run()
    assert len(report.triggered) == 5
    assert len(devin.calls) == 5
    # prompt mentions research and not forcing
    assert any("Research first" in c["prompt"] for c in devin.calls)
    assert any("do NOT force" in c["prompt"] for c in devin.calls)


def test_run_respects_max_sessions(tmp_path):
    runner, devin = make_runner(tmp_path, max_sessions_per_run=2)
    report = runner.run()
    assert len(report.triggered) == 2
    assert len(devin.calls) == 2
    skipped = [r for r in report.results if not r.triggered]
    assert any("max_sessions_per_run" in (r.skipped_reason or "") for r in skipped)


def test_dedup_skips_already_triggered(tmp_path):
    runner, devin = make_runner(tmp_path)
    runner.run()
    assert len(devin.calls) == 5

    # Second run with same state + same latest versions should trigger nothing new.
    runner2, devin2 = make_runner(tmp_path)
    report2 = runner2.run()
    assert len(devin2.calls) == 0
    assert all(not r.triggered for r in report2.results)


def test_dry_run_creates_no_sessions(tmp_path):
    runner, devin = make_runner(tmp_path)
    report = runner.run(dry_run=True)
    assert len(devin.calls) == 0
    assert all(not r.triggered for r in report.results)


def test_registry_error_recorded(tmp_path):
    cfg = make_config(tmp_path)

    class BrokenRegistry:
        def latest_version(self, ecosystem, name):
            from dep_automation.registries import RegistryError

            raise RegistryError("network down")

    runner = Runner(
        cfg, registry=BrokenRegistry(), devin=FakeDevin(), state=State.load(cfg.state_path)
    )
    report = runner.run()
    assert report.errors
    assert len(report.triggered) == 0


def test_requires_manifest_change_flag(tmp_path):
    runner, _ = make_runner(tmp_path)
    by_name = {od.name: od for od in runner.find_outdated()}
    assert by_name["pandas"].requires_manifest_change is True
