from dep_automation.metrics import Outcome
from dep_automation.sample import build_sample_report, sample_history, sample_sessions


def test_sample_report_is_fully_populated():
    report = build_sample_report()
    data = report.to_dict()

    # Cards have real numbers.
    assert data["totals"]["sessions"] == len(sample_sessions())
    assert data["totals"]["prs_merged"] > 0
    assert data["totals"]["prs_open"] > 0
    assert data["totals"]["acus_consumed"] > 0
    assert data["totals"]["success_rate_pct"] is not None

    # Every chart/table has rows.
    assert sum(data["by_outcome"].values()) == data["totals"]["sessions"]
    assert data["sessions"]
    assert report.history

    # Coverage + rework signals are present.
    assert data["coverage"]["pct_optimized"] > 0
    assert data["rework"]["pct_prs_needing_changes"] is not None


def test_sample_report_covers_multiple_outcomes():
    by_outcome = build_sample_report().by_outcome
    populated = {o for o, n in by_outcome.items() if n}
    assert {Outcome.PR_MERGED, Outcome.PR_OPEN, Outcome.COMPLETED_NO_PR} <= populated


def test_sample_report_without_coverage():
    assert build_sample_report(coverage=False).coverage is None


def test_sample_history_has_timestamps():
    history = sample_history()
    assert history
    assert all("timestamp" in row for row in history)
