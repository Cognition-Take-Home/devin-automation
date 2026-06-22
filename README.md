# devin-automation

Nightly **library usage-optimization** automation for the
[`Cognition-Take-Home/superset`](https://github.com/Cognition-Take-Home/superset)
repository, driven by the [Devin API](https://docs.devin.ai/api-reference/v1/sessions/create-a-new-devin-session).

Each night it hands Devin a short list of the libraries superset uses most heavily and
asks it to deep-dive **one** of them: study how the repo actually uses the library, compare
that against the library's docs, and make small, safe improvements to that usage — or open
no PR if nothing is worthwhile. It is not a version bumper; see
[What it does](#what-it-does) below.

## Running it

The same CLI runs three things, all shown below:

| Command | What it does |
| --- | --- |
| `shortlist` | Show the ranked candidate libraries this run would consider (no session) |
| `optimize [--dry-run]` | The nightly run: shortlist + create **one** Devin session (`--dry-run` previews only) |
| `report [--sync] [--coverage]` | Effectiveness metrics (outcomes, success rate, throughput, coverage, rework) |

`--dry-run` and `shortlist`/`report` need **no** API key. Actually creating a session
(`optimize`, `single … --go`) needs `DEVIN_API_KEY` (and `DEVIN_ORG_ID` for the v3 API).

The automation reads the target repo (superset) from a local checkout to measure usage; it
never pushes to superset — Devin opens the PRs.

### With Docker (recommended)

No Python or ripgrep setup needed — the image bundles everything. Requires Docker (on
macOS/Windows that means **Docker Desktop must be running** — `docker info` should succeed).

```bash
export DEVIN_API_KEY=...  DEVIN_ORG_ID=org-...
# SUPERSET_PATH defaults to ../superset; override if your checkout is elsewhere.
export SUPERSET_PATH=../superset

docker compose run --rm automation shortlist           # show candidate ranking
docker compose run --rm automation optimize --dry-run  # preview the nightly run
docker compose run --rm automation optimize            # create one Devin session
docker compose run --rm automation report --coverage   # effectiveness report

docker compose run --rm single cryptography            # ad-hoc one dep (dry run)
docker compose run --rm single cryptography --go       # ad-hoc one dep (create session)

docker compose up dashboard                             # marimo UI at http://localhost:2718
```

Compose builds the image on first use. If you upgraded the code, **force a rebuild** so you
don't run a cached older image: `docker compose build` (or add `--build` to a `run`).
The target repo is mounted read-only; `state/` is mounted so rotation state and run history
persist across runs.

### Without Docker (native Python)

**Prerequisites:** Python 3.10+ and [**ripgrep**](https://github.com/BurntSushi/ripgrep)
(`rg`) on your PATH — the usage scan shells out to it. Install ripgrep with
`brew install ripgrep` (macOS) or `apt-get install ripgrep` (Debian/Ubuntu).

```bash
pip install -e .                                       # add "[dashboard]" for the marimo UI
export DEVIN_API_KEY=...  DEVIN_ORG_ID=org-...         # only needed to create a session

dep-automation --target-repo-path ../superset shortlist
dep-automation --target-repo-path ../superset optimize --dry-run
dep-automation --target-repo-path ../superset optimize
dep-automation --target-repo-path ../superset report --sync --coverage

# Ad-hoc: optimize one named library now (positional arg; pypi or npm auto-detected)
python run_single.py cryptography                      # dry run (creates nothing)
python run_single.py cryptography --go                 # create one session

# Dashboard (needs the [dashboard] extra)
marimo run dashboard.py                                # http://localhost:2718
```

`report` extras: `--json` / `--markdown` switch the format; `--sync` refreshes live session
status + PRs from the Devin API; `--coverage` measures how much of the library set has been
optimized. The dashboard reads its config path from `$DEP_AUTOMATION_CONFIG` (default
`config.yaml`).

## What it does

Bumping versions is a commodity (Dependabot/Renovate) and drags you into dependency
resolution, lockfile conflicts, and coupled-package families. "Use the libraries you
already have *better*" plays to Devin's strengths — reading code and docs and making
judgment calls — and each night produces at most one small, self-contained, reviewable PR
with no cross-branch coupling. Each session is asked to:

1. **Pick one** library from the shortlist where it can find the most genuine, low-risk
   improvement.
2. **Study usage vs. docs** — find the repo's call sites, then read the library's official
   documentation/API reference for the installed version.
3. **Make small, safe improvements** — deprecated APIs still in use, redundant workarounds
   the library now makes unnecessary, simpler/idiomatic calls, easy correctness/perf wins.
4. **Bump only when it's small and safe** — if (and only if) a newer version unlocks a
   distinctly better usage and the bump is mechanical, it may update the version + lockfile
   and adopt the improvement in the same PR. A library that is several majors behind or
   would need a big migration is skipped instead (`allow_safe_bumps: false` forbids any
   version change).
5. **Open no PR if nothing is worthwhile** — a no-op night is a valid, expected result; it
   avoids low-value churn. Anything large or risky is documented as a suggested follow-up
   rather than forced, and tests/lint/types are never weakened.

The full instruction set lives in
[`src/dep_automation/prompts.py`](src/dep_automation/prompts.py).

## How it works

```
manifests (pyproject.toml, package.json)
        │  parse top-level deps only
        ▼
   usage scan (ripgrep)  ──►  rank deps by how heavily the repo uses each
        │
        ▼
   selection  ──►  drop deps considered within the cooldown window (rotation),
        │          take the top N most-used → shortlist
        ▼
   Devin API: ONE session, given the shortlist
        │  Devin picks one library and improves its usage
        ▼
   draft PR on superset  (titled  opt(<package>): …)   — or no PR at all
```

- **Top-level only** — reads `[project].dependencies` from `pyproject.toml` and
  `dependencies`/`devDependencies` from `package.json`. Lock files / transitive trees are
  ignored. `file:`/`git:`/`workspace:` specifiers are skipped.
- **Usage ranking** — [`usage.py`](src/dep_automation/usage.py) uses ripgrep to count how
  often each package's import name appears in the source trees (anchored so short names
  aren't inflated by substring hits). This is a cheap harness-side heuristic just to rank
  candidates; Devin makes the real call.
- **Rotation / cooldown** — [`state/processed.json`](state/processed.json) records when
  each dependency was last *considered* (shortlisted) and last *optimized* (chosen +
  produced a PR). A dependency shortlisted within `cooldown_days` is skipped, so the
  automation rotates across the whole library set over time instead of re-poking the same
  few. The chosen package is resolved from the PR's `opt(<package>): …` title on sync.

## Triggering (nightly)

This runs **nightly** via GitHub Actions' built-in `schedule:` cron (no always-on VM — the
scheduler spins up an ephemeral runner, runs the CLI for a few minutes, then tears it
down). It also supports `workflow_dispatch` (manual runs, with a dry-run toggle) and
`repository_dispatch` (type `optimize-now`, to kick off a run on demand). See
[`.github/workflows/dependency-automation.yml`](.github/workflows/dependency-automation.yml).

## Analytics & reporting — "how do I know it's working?"

The system records every optimization session it starts in
[`state/processed.json`](state/processed.json) (the candidate shortlist, the package Devin
chose, and — after a `--sync` — that session's live status, any PR it opened, ACUs
consumed, and follow-up commit counts). Each run also appends a line to
`state/history.jsonl` (checked / shortlisted / triggered / errors). The `report` command
turns this into the signals an engineering leader cares about:

- **Outcomes** of every session — *PR merged*, *PR open (awaiting review)*, *active*,
  *blocked (needs input)*, *ended without a PR* (Devin found nothing worth changing — a
  valid result), or *unknown (not synced)*.
- **Success rate** — share of *finished* sessions that produced a PR.
- **Coverage** (`--coverage`) — how much of the dependency set has been optimized at least
  once, and how much has been considered.
- **Throughput over time** — sessions shortlisted/triggered per run, from the history log.
- **Rework** — after Devin opens a PR, how many *follow-up commits* the branch needed
  (treating the first commit as Devin's initial work, splitting human vs. Devin
  follow-ups). Reported as *% of PRs that needed additional changes* and *avg follow-up
  commits/PR* — a direct "how landable is the first pass?" signal. Commit data is read with
  the authenticated `gh` CLI; the metric is omitted gracefully when unavailable.
- **Cost** — total ACUs consumed.

In CI the workflow runs `report --sync --coverage` every run and publishes the Markdown to
the **GitHub Actions run summary** (via `$GITHUB_STEP_SUMMARY`), so a leader just opens the
latest run to see the dashboard. Example:

```
Coverage: 4/315 deps optimized at least once (1.3%); 12 considered
Sessions: 4  |  active: 0  |  completed: 4
PRs: 2 open, 1 merged  |  success rate: 75.0%  |  ACUs: 6.0
Rework: 25.0% of PRs needed follow-up commits (avg 0.5/PR, 1 human)

By outcome:
  PR merged              1
  PR open (review)       2
  ended, no change       1

Across 4 run(s): shortlisted 20, triggered 4, errors 0
```

The [marimo](https://marimo.io) dashboard ([`dashboard.py`](dashboard.py)) renders the same
metrics interactively — KPI cards, an outcomes bar chart, a throughput line chart, and a
sortable sessions table, with a reactive toggle to sync live data. Launch it with
`docker compose up dashboard` or `marimo run dashboard.py` (see [Running it](#running-it)).

## Configuration

Behavior is configured in [`config.yaml`](config.yaml): target repo, manifests, shortlist
size, `cooldown_days`, `allow_safe_bumps`, per-ecosystem usage paths, ignore/only lists, and
Devin options.

The GitHub Actions workflow additionally needs:

- `DEVIN_API_KEY` *(secret)* — a Devin `cog_` service-user key / PAT
  (Settings → Secrets → Actions).
- `DEVIN_ORG_ID` *(variable)* — your organization id (prefix `org-`), required by the v3
  API (Settings → Variables → Actions). Can also be set via `devin.org_id` in `config.yaml`.
- `TARGET_REPO_TOKEN` *(optional secret)* — a token with read access to the target repo if
  it is private and the default `GITHUB_TOKEN` cannot read it.

The Devin client uses the current **v3** org-scoped API
(`POST /v3/organizations/{org_id}/sessions`) by default; set `devin.api_version: v1` to use
the legacy endpoint.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```
