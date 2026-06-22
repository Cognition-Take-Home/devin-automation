"""Hacky, hardcoded single-dependency run — for local testing only.

Runs a library *usage optimization* for exactly ONE named dependency (instead of the
nightly shortlist), opening exactly ONE Devin session. No config files, no fan-out.

    export DEVIN_API_KEY=...
    export DEVIN_ORG_ID=org-...
    python run_single.py cryptography          # dry run (no session created)
    python run_single.py cryptography --go      # actually create the session
    python run_single.py react-window --go      # works for npm deps too

The package name is matched against superset's top-level manifests (pyproject.toml and
superset-frontend/package.json), so it works for any dependency in either ecosystem.
"""

import argparse
import os
from pathlib import Path

from dep_automation.config import Config
from dep_automation.devin import DevinClient
from dep_automation.manifests import parse_manifest
from dep_automation.models import Candidate, Ecosystem
from dep_automation.prompts import build_optimization_prompt, build_optimization_title
from dep_automation.usage import UsageScanner

# --- hardcoded knobs ---------------------------------------------------------
REPO = "Cognition-Take-Home/superset"
# Local checkout of the target repo; override with TARGET_REPO_PATH (e.g. in Docker).
REPO_PATH = os.environ.get("TARGET_REPO_PATH") or os.path.expanduser("~/repos/superset")
# Where to look for each ecosystem's top-level dependency list.
MANIFESTS = {
    Ecosystem.PYPI: "pyproject.toml",
    Ecosystem.NPM: "superset-frontend/package.json",
}
USAGE_PATHS = {"pypi": ["superset"], "npm": ["superset-frontend/src"]}
# -----------------------------------------------------------------------------


def find_dependency(package: str):
    """Return the Dependency for the first manifest that lists `package`."""
    for manifest in MANIFESTS.values():
        for dep in parse_manifest(Path(REPO_PATH), manifest):
            if dep.name.lower() == package.lower():
                return dep
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize how the repo uses one library.")
    parser.add_argument("package", help="dependency name, e.g. cryptography or react-window")
    parser.add_argument("--go", action="store_true", help="actually create the Devin session")
    args = parser.parse_args()

    dep = find_dependency(args.package)
    if dep is None:
        print(f"{args.package} not found in {REPO}'s top-level manifests")
        return 1

    config = Config(
        target_repo=REPO,
        target_repo_path=REPO_PATH,
        usage_paths=USAGE_PATHS,
    )
    usage = UsageScanner(config).count(dep)
    candidate = Candidate(dependency=dep, usage=usage)
    print(f"[{dep.ecosystem.value}] {args.package}: {dep.constraint!r} (~{usage} usages)")

    prompt = build_optimization_prompt([candidate], config)
    title = build_optimization_title()

    if not args.go:
        print("\n[dry run] would create ONE Devin optimization session:")
        print(f"  title: {title}")
        print("Re-run with --go to actually create it.")
        return 0

    client = DevinClient(org_id=os.environ.get("DEVIN_ORG_ID"), api_version="v3")
    session = client.create_session(prompt, title=title, tags=["dependency-optimization"])
    print(f"\nCreated session: {session.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
