from dep_automation.metrics import (
    Coverage,
    Outcome,
    build_report,
    classify,
    render_markdown,
    render_text,
)
from dep_automation.state import SessionEntry


def _entry(name, **kw):
    base = dict(session_id=name, chosen_name=name, chosen_ecosystem="pypi")
    base.update(kw)
    return SessionEntry(**base)


def test_classify_outcomes():
    assert classify(_entry("a", pr_state="merged", pr_url="u")) is Outcome.PR_MERGED
    assert classify(_entry("b", pr_url="u")) is Outcome.PR_OPEN
    assert classify(_entry("c", status="running")) is Outcome.ACTIVE
    assert classify(_entry("d", status="blocked")) is Outcome.BLOCKED
    assert classify(_entry("e", status="finished")) is Outcome.COMPLETED_NO_PR
    assert classify(_entry("f")) is Outcome.UNKNOWN


def test_coverage_math():
    cov = Coverage(total=200, optimized=50, considered=80)
    assert cov.pct_optimized == 25.0


def test_coverage_zero_total():
    assert Coverage(total=0, optimized=0, considered=0).pct_optimized == 0.0


def test_report_aggregates_and_success_rate():
    entries = [
        _entry("merged1", pr_state="merged", pr_url="u1"),
        _entry("open1", pr_url="u2"),
        _entry("open2", pr_url="u3"),
        _entry("active1", status="running"),
        _entry("noprr", status="finished"),
        _entry("unknown1"),  # excluded from success-rate denominator
    ]
    report = build_report(entries, coverage=Coverage(100, 10, 20))
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
        {"checked": 10, "shortlisted": 5, "triggered": 1, "errors": 0},
        {"checked": 10, "shortlisted": 5, "triggered": 1, "errors": 1},
    ]
    report = build_report([], history=history)
    totals = report.history_totals
    assert totals["triggered"] == 2
    assert totals["shortlisted"] == 10
    assert totals["errors"] == 1


def test_report_rework_aggregates():
    entries = [
        _entry("a", pr_url="u1", followup_commits=0, human_followup_commits=0),
        _entry("b", pr_url="u2", followup_commits=3, human_followup_commits=2),
        _entry("c", pr_url="u3", followup_commits=1, human_followup_commits=0),
        _entry("d"),  # no commit data -> excluded from rework denominator
    ]
    report = build_report(entries)
    assert report.prs_with_followups == 2  # b and c
    assert report.total_followup_commits == 4
    assert report.total_human_followup_commits == 2
    assert report.pct_prs_needing_changes == round(100 * 2 / 3, 1)
    assert report.avg_followup_commits == round(4 / 3, 2)


def test_report_rework_none_without_data():
    report = build_report([_entry("a", pr_url="u")])
    assert report.pct_prs_needing_changes is None
    assert report.avg_followup_commits is None
    d = report.to_dict()
    assert d["rework"]["prs_with_commit_data"] == 0


def test_report_to_dict_and_renderers():
    entries = [
        _entry("react", chosen_ecosystem="npm", pr_url="u"),
        _entry("gunicorn", status="running"),
    ]
    report = build_report(entries, coverage=Coverage(50, 5, 10))
    d = report.to_dict()
    assert d["totals"]["sessions"] == 2
    assert d["coverage"]["pct_optimized"] == 10.0
    assert d["sessions"][0]["package"] == "react"

    text = render_text(report)
    assert "react" in text and "PR open" in text

    md = render_markdown(report)
    assert md.startswith("## Dependency optimization report")
    assert "| Package |" in md
    assert "[PR](u)" in md


def test_pending_choice_display():
    entry = SessionEntry(session_id="s1", status="running")
    report = build_report([entry])
    assert "(pending choice)" in render_text(report)
