# devin-automation

Research-led **dependency-management automation** for the
[`Cognition-Take-Home/superset`](https://github.com/Cognition-Take-Home/superset)
repository, driven by the [Devin API](https://docs.devin.ai/api-reference/v1/sessions/create-a-new-devin-session).

It inspects the **top-level** dependencies of the target repo, compares each one against
the latest version published on its registry (PyPI / npm), and — for releases that need a
manifest change to adopt — opens a Devin session that performs a *careful, research-led*
upgrade instead of a blind version bump.

## What makes this different from a plain version bumper

Tools like Dependabot/Renovate bump the number and let CI tell you what broke. This
automation instead asks Devin to:

1. **Research first** — read the changelog / release notes / migration guides for every
   release between the current and latest version and summarize what actually changed.
2. **Adopt improvements thoughtfully** — take advantage of new APIs, performance wins,
   and the chance to remove old workarounds where it's clearly beneficial and low-risk.
3. **Never force changes** — risky or large adoptions are *documented as suggested
   follow-ups in the PR*, not pushed. Tests, type checks, and lint are never weakened to
   make things pass. The PR is opened as a draft for human review.

The full instruction set lives in
[`src/dep_automation/prompts.py`](src/dep_automation/prompts.py).

## How it works

```
manifests (pyproject.toml, package.json)
        │  parse top-level deps only
        ▼
   registries (PyPI / npm)  ──►  is the latest release outside the current constraint?
        │                                         │ yes
        ▼                                         ▼
   de-dup state  ──►  not seen before?  ──►  Devin API: create session (research-led upgrade)
                                                  │
                                                  ▼
                                        draft PR on superset
```

- **Top-level only** — reads `[project].dependencies` from `pyproject.toml` and
  `dependencies`/`devDependencies` from `package.json`. Lock files / transitive trees are
  ignored. `file:`/`git:`/`workspace:` specifiers are skipped.
- **Outdated detection** — by default (`trigger_policy: out-of-range`) a dependency is
  flagged only when the latest release is **not permitted by the current constraint**
  (i.e. a manifest edit is genuinely required). `any-newer` flags any newer release.
- **De-duplication** — [`state/processed.json`](state/processed.json) records the latest
  version each dependency was last triggered for, so polling doesn't re-open sessions.

## Triggering: events vs. polling

PyPI and npm do **not** offer consumer-facing push webhooks for third-party packages (you
can only subscribe to releases of packages you own), so a true "package released" event is
not available for superset's dependencies. The automation therefore **polls on a
schedule** via GitHub Actions, and additionally supports:

- `workflow_dispatch` — manual runs (with a dry-run toggle).
- `repository_dispatch` (type `dependency-release`) — so any external release-watcher you
  wire up can push an event to trigger a run on demand.

See [`.github/workflows/dependency-automation.yml`](.github/workflows/dependency-automation.yml).

## Usage

```bash
pip install -e .

# List the top-level dependencies discovered in the target repo
dep-automation --target-repo-path ../superset list

# Report which dependencies are outdated (no Devin sessions created)
dep-automation --target-repo-path ../superset check
dep-automation --target-repo-path ../superset check --json

# Preview what would be triggered, without creating sessions
dep-automation --target-repo-path ../superset run --dry-run

# Create Devin sessions for outdated dependencies (needs DEVIN_API_KEY)
export DEVIN_API_KEY=...
dep-automation --target-repo-path ../superset run

# Effectiveness report: outcomes, success rate, throughput, drift
dep-automation report                      # from local state
dep-automation report --sync               # refresh live status + PRs from the Devin API
dep-automation report --sync --coverage    # also measure current drift
dep-automation report --json               # machine-readable
dep-automation report --markdown           # Markdown (used for the CI run summary)
```

Configuration lives in [`config.yaml`](config.yaml) (target repo, manifests, trigger
policy, ignore list, max sessions per run, Devin options).

## Analytics & reporting — "how do I know it's working?"

The system records every upgrade it starts in [`state/processed.json`](state/processed.json)
(package, version, update size, the Devin session, and — after a `--sync` — that session's
live status, any PR it opened, and ACUs consumed). Each run also appends a line to
`state/history.jsonl` (checked / outdated / triggered / errors). The `report` command turns
this into the signals an engineering leader cares about:

- **Outcomes** of every triggered upgrade — *PR merged*, *PR open (awaiting review)*,
  *active*, *blocked (needs input)*, *ended without a PR*, or *unknown (not synced)*.
- **Success rate** — share of *finished* sessions that produced a PR.
- **Drift / coverage** (`--coverage`) — how many tracked deps are currently behind; the
  backlog the system is working down.
- **Throughput over time** — sessions triggered and drift per run, from the history log.
- **Rework** — after Devin opens a PR, how many *follow-up commits* the branch needed
  (treating the first commit as Devin's initial work, and splitting human vs. Devin
  follow-ups). Reported as *% of PRs that needed additional changes* and *avg follow-up
  commits/PR* — a direct "how landable is the first pass?" signal. Commit data is read with
  the authenticated `gh` CLI; the metric is omitted gracefully when unavailable.
- **Cost** — total ACUs consumed.

In CI the workflow runs `report --sync --coverage` every run and publishes the Markdown to
the **GitHub Actions run summary** (via `$GITHUB_STEP_SUMMARY`), so a leader just opens the
latest run to see the dashboard. Example:

```
Upgrades tracked: 3  |  active: 0  |  completed: 3
PRs: 2 open, 0 merged  |  success rate: 66.7%  |  ACUs: 0.0
Rework: 0.0% of PRs needed follow-up commits (avg 0.0/PR, 0 human)

By outcome:
  PR open (review)       2
  ended, no PR           1

Across 3 run(s): checked 952, outdated 240, triggered 3, errors 0
```

### Interactive dashboard (marimo)

For a richer, clickable view there's a [marimo](https://marimo.io) notebook,
[`dashboard.py`](dashboard.py), that renders the same metrics as KPI cards, an outcomes bar
chart, a throughput line chart, and a sortable upgrades table — with a reactive toggle to
sync live data:

```bash
pip install -e ".[dashboard]"
marimo run dashboard.py     # read-only app   (or: marimo edit dashboard.py)
```

It reads the config path from `$DEP_AUTOMATION_CONFIG` (default `config.yaml`).

## Configuration in CI

The workflow needs:

- `DEVIN_API_KEY` *(secret)* — a Devin `cog_` service-user key / PAT
  (Settings → Secrets → Actions).
- `DEVIN_ORG_ID` *(variable)* — your organization id (prefix `org-`), required by the v3
  API (Settings → Variables → Actions). Can also be set via `devin.org_id` in `config.yaml`.
- `TARGET_REPO_TOKEN` *(optional secret)* — a token with read access to the target repo if
  it is private and the default `GITHUB_TOKEN` cannot read it.

The Devin client uses the current **v3** org-scoped API
(`POST /v3/organizations/{org_id}/sessions`) by default; set `devin.api_version: v1` to use
the legacy endpoint.

## Docker

The whole app runs in a container — see [`Dockerfile`](Dockerfile) and
[`docker-compose.yml`](docker-compose.yml). The image bundles the CLI, the marimo
dashboard, and `git`/`gh` (the latter powers the rework metric). The target repo
(superset) is mounted read-only; `state/` is mounted so de-dup state and run history
persist across runs.

```bash
export DEVIN_API_KEY=...  DEVIN_ORG_ID=org-...
# SUPERSET_PATH defaults to ../superset; override if your checkout is elsewhere.

docker compose run --rm automation check            # list outdated deps
docker compose run --rm automation run --dry-run    # preview sessions
docker compose run --rm automation run              # create Devin sessions
docker compose up dashboard                          # marimo UI at http://localhost:2718
```

Or without compose:

```bash
docker build -t devin-automation .
docker run --rm -e DEVIN_API_KEY -e DEVIN_ORG_ID \
  -v "$PWD/state:/app/state" -v "/path/to/superset:/superset:ro" \
  devin-automation --target-repo-path /superset check
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```
