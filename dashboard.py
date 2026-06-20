"""Marimo dashboard for the dependency-automation effectiveness metrics.

Run it:

    pip install -e ".[dashboard]"
    marimo run dashboard.py            # read-only app
    marimo edit dashboard.py           # editable notebook

Config path is read from $DEP_AUTOMATION_CONFIG (defaults to ``config.yaml``). The
"Sync from APIs" toggle pulls live session status + PR commit counts; it needs
``DEVIN_API_KEY`` (and ``gh`` auth for commit data) and degrades gracefully without them.
"""

import marimo

app = marimo.App(width="medium")


@app.cell
def _():
    import os

    import altair as alt
    import pandas as pd

    import marimo as mo
    from dep_automation.config import Config
    from dep_automation.runner import Runner

    return Config, Runner, alt, mo, os, pd


@app.cell
def _(mo):
    sync = mo.ui.checkbox(label="Sync live status + PR commits from APIs")
    coverage = mo.ui.checkbox(label="Compute current drift (slower)", value=True)
    mo.hstack([sync, coverage], justify="start")
    return coverage, sync


@app.cell
def _(Config, Runner, coverage, mo, os, sync):
    config_path = os.environ.get("DEP_AUTOMATION_CONFIG", "config.yaml")
    runner = Runner(Config.from_file(config_path))

    sync_note = ""
    if sync.value:
        try:
            n = runner.sync_statuses()
            sync_note = f"Synced {n} session(s) from the Devin API."
        except Exception as exc:  # noqa: BLE001 - surface any auth/network issue in the UI
            sync_note = f"Sync failed: {exc}"

    report = runner.build_report(coverage=coverage.value)
    data = report.to_dict()
    mo.md(f"_Config: `{config_path}` — generated {data['generated_at']}._ {sync_note}")
    return data, report


@app.cell
def _(data, fmt_pct, mo):
    t = data["totals"]
    cov = data.get("coverage")
    rework = data["rework"]

    def stat(label, value):
        return mo.stat(value=value, label=label)

    cards = [
        stat("Upgrades tracked", t["tracked_upgrades"]),
        stat("Active", t["active"]),
        stat("PRs open", t["prs_open"]),
        stat("PRs merged", t["prs_merged"]),
        stat("Success rate", fmt_pct(t["success_rate_pct"])),
        stat("ACUs", t["acus_consumed"]),
    ]
    if cov:
        cards.append(stat("Up to date", fmt_pct(cov["pct_up_to_date"])))
    if rework["pct_prs_needing_changes"] is not None:
        cards.append(stat("PRs needing rework", fmt_pct(rework["pct_prs_needing_changes"])))

    mo.vstack([mo.md("## Dependency automation — effectiveness"), mo.hstack(cards, wrap=True)])
    return


@app.cell
def _(alt, data, mo, pd):
    _rows = [{"outcome": k, "count": v} for k, v in data["by_outcome"].items() if v]
    if _rows:
        _chart = (
            alt.Chart(pd.DataFrame(_rows))
            .mark_bar()
            .encode(
                x=alt.X("count:Q", title="Upgrades"),
                y=alt.Y("outcome:N", sort="-x", title=None),
                color=alt.Color("outcome:N", legend=None),
                tooltip=["outcome", "count"],
            )
            .properties(height=200, title="Outcomes")
        )
        _out = mo.ui.altair_chart(_chart)
    else:
        _out = mo.md("_No tracked upgrades yet._")
    _out
    return


@app.cell
def _(alt, mo, pd, report):
    if report.history:
        _df = pd.DataFrame(report.history)
        _df["run"] = range(1, len(_df) + 1)
        _long = _df.melt(
            id_vars=["run"],
            value_vars=[c for c in ("checked", "outdated", "triggered", "errors") if c in _df],
            var_name="metric",
            value_name="value",
        )
        _chart = (
            alt.Chart(_long)
            .mark_line(point=True)
            .encode(
                x=alt.X("run:O", title="Run"),
                y=alt.Y("value:Q", title="Count"),
                color="metric:N",
                tooltip=["run", "metric", "value"],
            )
            .properties(height=220, title="Throughput over time")
        )
        _out = mo.ui.altair_chart(_chart)
    else:
        _out = mo.md("_No run history yet (run the automation to accumulate `history.jsonl`)._")
    _out
    return


@app.cell
def _(data, mo, pd):
    if data["upgrades"]:
        _df = pd.DataFrame(data["upgrades"])[
            [
                "name",
                "ecosystem",
                "version",
                "update_kind",
                "outcome",
                "followup_commits",
                "acus_consumed",
                "pr_url",
            ]
        ]
        _out = mo.ui.table(_df, selection=None, label="Tracked upgrades")
    else:
        _out = mo.md("_No upgrades tracked yet._")
    _out
    return


@app.cell
def _():
    def fmt_pct(value):
        return "n/a" if value is None else f"{value}%"

    return (fmt_pct,)


if __name__ == "__main__":
    app.run()
