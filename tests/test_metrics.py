from dep_automation.metrics import (
    Coverage,
    Outcome,
    build_report,
    classify,
    render_markdown,
    render_text,
)
from dep_automation.state import StateEntry


def _entry(name, **kw):
    base = dict(name=name, ecosystem="pypi", version="1.0.0")
    base.update(kw)
    return StateEntry(**base)


def test_classify_outcomes():
    assert classify(_entry("a", pr_state="merged", pr_url="u")) is Outcome.PR_MERGED
    assert classify(_entry("b", pr_url="u")) is Outcome.PR_OPEN
    assert classify(_entry("c", status="running")) is Outcome.ACTIVE
    assert classify(_entry("d", status="blocked")) is Outcome.BLOCKED
    assert classify(_entry("e", status="finished")) is Outcome.COMPLETED_NO_PR
    assert classify(_entry("f")) is Outcome.UNKNOWN


def test_coverage_math():
    cov = Coverage(checked=200, outdated=50)
    assert cov.up_to_date == 150
    assert cov.pct_up_to_date == 75.0


def test_coverage_zero_checked():
    assert Coverage(checked=0, outdated=0).pct_up_to_date == 0.0


def test_report_aggregates_and_success_rate():
    entries = [
        _entry("merged1", pr_state="merged", pr_url="u1"),
        _entry("open1", pr_url="u2"),
        _entry("open2", pr_url="u3"),
        _entry("active1", status="running"),
        _entry("noprr", status="finished"),
        _entry("unknown1"),  # excluded from success-rate denominator
    ]
    report = build_report(entries, coverage=Coverage(100, 10))
    assert report.total == 6
    assert report.prs_open == 2
    assert report.prs_merged == 1
    assert report.active == 1
    # completed (terminal) = merged(1) + open(2) + completed_no_pr(1) = 4
    assert report.completed == 4
    # produced PR (3) / completed (4) = 75%
    assert report.success_rate == 75.0


def test_report_success_rate_none_when_nothing_finished():
    report = build_report([_entry("a", status="running"), _entry("b")])
    assert report.success_rate is None


def test_report_throughput_from_history():
    history = [
        {"checked": 10, "outdated": 4, "triggered": 4, "errors": 0},
        {"checked": 10, "outdated": 2, "triggered": 1, "errors": 1},
    ]
    report = build_report([], history=history)
    totals = report.history_totals
    assert totals["triggered"] == 5
    assert totals["outdated"] == 6
    assert totals["errors"] == 1


def test_report_to_dict_and_renderers():
    entries = [
        _entry("react", ecosystem="npm", version="19.0.0", update_kind="major", pr_url="u"),
        _entry("gunicorn", version="26.0.0", update_kind="major", status="running"),
    ]
    report = build_report(entries, coverage=Coverage(50, 5))
    d = report.to_dict()
    assert d["totals"]["tracked_upgrades"] == 2
    assert d["coverage"]["pct_up_to_date"] == 90.0
    assert d["by_ecosystem"]["npm"] == 1

    text = render_text(report)
    assert "react" in text and "PR open" in text

    md = render_markdown(report)
    assert md.startswith("## Dependency automation report")
    assert "| Package |" in md
    assert "[PR](u)" in md
