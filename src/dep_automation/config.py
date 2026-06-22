"""Configuration loading for the dependency usage-optimization automation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import Ecosystem


@dataclass
class ManifestSpec:
    path: str
    include_optional: bool = False  # pyproject optional-dependencies
    include_dev: bool = True  # package.json devDependencies


@dataclass
class Config:
    # --- target repository -------------------------------------------------
    target_repo: str  # "owner/repo" used in the Devin prompt and PRs
    target_repo_path: str  # local checkout path used to read manifests + measure usage
    base_branch: str = "master"
    manifests: list[ManifestSpec] = field(default_factory=list)

    # --- candidate selection ----------------------------------------------
    ignore: list[str] = field(default_factory=list)  # package names to never optimize
    only: list[str] = field(default_factory=list)  # if set, restrict to these names
    # How many candidates to put in front of Devin each run (it picks one).
    shortlist_size: int = 5
    # Don't reconsider a dependency that was shortlisted within this many days, so the
    # automation rotates across the library set instead of re-poking the same few.
    cooldown_days: int = 30
    # Where (relative to the repo) to measure each ecosystem's usage. Defaults to the
    # whole repo if a given ecosystem is not listed.
    usage_paths: dict[str, list[str]] = field(default_factory=dict)

    # --- Devin -------------------------------------------------------------
    devin_api_base: str = "https://api.devin.ai"
    devin_api_version: str = "v3"
    devin_org_id: str | None = None  # required by v3; falls back to $DEVIN_ORG_ID
    devin_max_acu_limit: int | None = None
    devin_tags: list[str] = field(default_factory=lambda: ["dependency-optimization"])
    devin_idempotent: bool = True
    create_draft_pr: bool = True

    # --- state -------------------------------------------------------------
    state_path: str = "state/processed.json"
    # Append-only log of each run (for throughput / progress-over-time reporting).
    history_path: str = "state/history.jsonl"

    def usage_paths_for(self, ecosystem: Ecosystem | str) -> list[str]:
        eco = ecosystem.value if isinstance(ecosystem, Ecosystem) else ecosystem
        return self.usage_paths.get(eco) or ["."]

    @staticmethod
    def from_file(path: str | Path) -> Config:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return Config.from_dict(raw)

    @staticmethod
    def from_dict(raw: dict) -> Config:
        manifests = [
            ManifestSpec(
                path=m["path"],
                include_optional=m.get("include_optional", False),
                include_dev=m.get("include_dev", True),
            )
            for m in raw.get("manifests", [])
        ]
        devin = raw.get("devin", {})
        return Config(
            target_repo=raw["target_repo"],
            target_repo_path=os.path.expanduser(raw.get("target_repo_path", "")),
            base_branch=raw.get("base_branch", "master"),
            manifests=manifests,
            ignore=raw.get("ignore", []),
            only=raw.get("only", []),
            shortlist_size=raw.get("shortlist_size", 5),
            cooldown_days=raw.get("cooldown_days", 30),
            usage_paths=raw.get("usage_paths", {}),
            devin_api_base=devin.get("api_base", "https://api.devin.ai"),
            devin_api_version=devin.get("api_version", "v3"),
            devin_org_id=devin.get("org_id") or os.environ.get("DEVIN_ORG_ID"),
            devin_max_acu_limit=devin.get("max_acu_limit"),
            devin_tags=devin.get("tags", ["dependency-optimization"]),
            devin_idempotent=devin.get("idempotent", True),
            create_draft_pr=devin.get("create_draft_pr", True),
            state_path=raw.get("state_path", "state/processed.json"),
            history_path=raw.get("history_path", "state/history.jsonl"),
        )
