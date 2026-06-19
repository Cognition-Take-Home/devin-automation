"""Configuration loading for the dependency automation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# When the latest release is already permitted by the current constraint, no manifest
# edit is required to adopt it. ``out-of-range`` only triggers Devin for updates that
# genuinely need a manifest change; ``any-newer`` triggers for any newer release.
TriggerPolicy = str  # "out-of-range" | "any-newer"


@dataclass
class ManifestSpec:
    path: str
    include_optional: bool = False  # pyproject optional-dependencies
    include_dev: bool = True  # package.json devDependencies


@dataclass
class Config:
    # --- target repository -------------------------------------------------
    target_repo: str  # "owner/repo" used in the Devin prompt and PRs
    target_repo_path: str  # local checkout path used to read manifests
    base_branch: str = "master"
    manifests: list[ManifestSpec] = field(default_factory=list)

    # --- selection ---------------------------------------------------------
    trigger_policy: TriggerPolicy = "out-of-range"
    allow_prerelease: bool = False
    ignore: list[str] = field(default_factory=list)  # package names to skip
    only: list[str] = field(default_factory=list)  # if set, restrict to these names
    max_sessions_per_run: int = 5

    # --- Devin -------------------------------------------------------------
    devin_api_base: str = "https://api.devin.ai"
    devin_max_acu_limit: int | None = None
    devin_tags: list[str] = field(default_factory=lambda: ["dependency-automation"])
    devin_idempotent: bool = True
    create_draft_pr: bool = True

    # --- state -------------------------------------------------------------
    state_path: str = "state/processed.json"

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
            trigger_policy=raw.get("trigger_policy", "out-of-range"),
            allow_prerelease=raw.get("allow_prerelease", False),
            ignore=raw.get("ignore", []),
            only=raw.get("only", []),
            max_sessions_per_run=raw.get("max_sessions_per_run", 5),
            devin_api_base=devin.get("api_base", "https://api.devin.ai"),
            devin_max_acu_limit=devin.get("max_acu_limit"),
            devin_tags=devin.get("tags", ["dependency-automation"]),
            devin_idempotent=devin.get("idempotent", True),
            create_draft_pr=devin.get("create_draft_pr", True),
        )
