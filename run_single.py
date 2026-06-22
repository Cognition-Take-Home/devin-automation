"""Hacky, hardcoded single-dependency run — for local testing only.

Checks exactly ONE dependency and, if it's behind, opens exactly ONE Devin session.
No config files, no fan-out.

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

from dep_automation.devin import DevinClient
from dep_automation.manifests import parse_manifest
from dep_automation.models import Ecosystem
from dep_automation.registries import RegistryClient
from dep_automation.versioning import classify_update, satisfies

# --- hardcoded knobs ---------------------------------------------------------
REPO = "Cognition-Take-Home/superset"
# Local checkout of the target repo; override with TARGET_REPO_PATH (e.g. in Docker).
REPO_PATH = os.environ.get("TARGET_REPO_PATH") or os.path.expanduser("~/repos/superset")
# Where to look for each ecosystem's top-level dependency list.
MANIFESTS = {
    Ecosystem.PYPI: "pyproject.toml",
    Ecosystem.NPM: "superset-frontend/package.json",
}
# -----------------------------------------------------------------------------


def find_dependency(package: str):
    """Return (ecosystem, dependency) for the first manifest that lists `package`."""
    for ecosystem, manifest in MANIFESTS.items():
        for dep in parse_manifest(Path(REPO_PATH), manifest):
            if dep.name.lower() == package.lower():
                return ecosystem, dep
    return None, None


def make_prompt(name: str, constraint: str, latest: str) -> str:
    return f"""\
Upgrade the dependency `{name}` in {REPO} to version {latest} \
(current constraint: `{constraint}`).

Do a RESEARCH-LED upgrade, not a blind bump:
1. Read {name}'s changelog/release notes between the current and {latest}.
2. Bump the constraint in the manifest, then adopt genuinely beneficial \
improvements the new version unlocks (new APIs, removable workarounds).
3. Do NOT force risky or breaking changes. If something is risky, leave the code \
as-is and list it under a "Deferred follow-ups" section in the PR.
4. Never weaken tests, lint, or types to make things pass. Run them.
5. Open a draft PR for review.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger one research-led upgrade session.")
    parser.add_argument("package", help="dependency name, e.g. cryptography or react-window")
    parser.add_argument("--go", action="store_true", help="actually create the Devin session")
    args = parser.parse_args()

    ecosystem, dep = find_dependency(args.package)
    if dep is None:
        print(f"{args.package} not found in {REPO}'s top-level manifests")
        return 1

    latest = RegistryClient().latest_version(ecosystem, args.package)
    in_range = satisfies(ecosystem, latest, dep.constraint) if dep.constraint else True
    kind = classify_update(ecosystem, dep.current_version, latest)
    print(
        f"[{ecosystem.value}] {args.package}: {dep.constraint!r} "
        f"-> latest {latest} ({kind.value})"
    )

    if in_range:
        print("Latest is already permitted by the constraint; nothing to do.")
        return 0

    prompt = make_prompt(args.package, dep.constraint or "", latest)
    title = f"deps: research-led upgrade of {args.package} -> {latest}"

    if not args.go:
        print("\n[dry run] would create ONE Devin session:")
        print(f"  title: {title}")
        print("Re-run with --go to actually create it.")
        return 0

    client = DevinClient(org_id=os.environ.get("DEVIN_ORG_ID"), api_version="v3")
    session = client.create_session(prompt, title=title, tags=["dependency-automation"])
    print(f"\nCreated session: {session.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
