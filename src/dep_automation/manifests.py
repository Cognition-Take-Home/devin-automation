"""Parse top-level dependencies out of a target repository's manifests.

Only *top-level / direct* dependencies are read - lock files and transitive trees are
intentionally ignored, per the automation's scope.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from .models import Dependency, Ecosystem
from .versioning import anchor

# PEP 508 requirement: name, optional extras, then the version specifier up to an
# environment marker (``;``).
_REQ_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*(?P<spec>[^;]*)"
)


def parse_pyproject(path: Path, *, include_optional: bool = False) -> list[Dependency]:
    """Parse ``[project].dependencies`` (and optionally optional-dependencies)."""
    data = tomllib.loads(path.read_text())
    project = data.get("project", {})
    raw: list[str] = list(project.get("dependencies", []))
    if include_optional:
        for group in project.get("optional-dependencies", {}).values():
            raw.extend(group)

    deps: list[Dependency] = []
    seen: set[str] = set()
    rel = path.name
    for requirement in raw:
        dep = _parse_requirement(requirement, rel)
        if dep and dep.name.lower() not in seen:
            seen.add(dep.name.lower())
            deps.append(dep)
    return deps


def _parse_requirement(requirement: str, manifest: str) -> Dependency | None:
    m = _REQ_RE.match(requirement)
    if not m:
        return None
    name = m.group("name")
    spec = m.group("spec").strip()
    return Dependency(
        name=name,
        ecosystem=Ecosystem.PYPI,
        constraint=spec,
        manifest=manifest,
        current_version=anchor(Ecosystem.PYPI, spec),
    )


def parse_package_json(
    path: Path, *, include_dev: bool = True
) -> list[Dependency]:
    """Parse ``dependencies`` (and optionally ``devDependencies``) from package.json."""
    data = json.loads(path.read_text())
    sections = ["dependencies"]
    if include_dev:
        sections.append("devDependencies")

    deps: list[Dependency] = []
    seen: set[str] = set()
    rel = str(path.name)
    for section in sections:
        for name, constraint in data.get(section, {}).items():
            if _is_non_registry(constraint):
                continue
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            deps.append(
                Dependency(
                    name=name,
                    ecosystem=Ecosystem.NPM,
                    constraint=constraint,
                    manifest=rel,
                    current_version=anchor(Ecosystem.NPM, constraint),
                )
            )
    return deps


def _is_non_registry(constraint: str) -> bool:
    """Skip workspace/file/git/url specifiers that have no registry to poll."""
    prefixes = ("file:", "link:", "workspace:", "git+", "git:", "http:", "https:", "npm:")
    if constraint.startswith(prefixes):
        return True
    # "owner/repo" / "owner/repo#tag" GitHub shorthand has no registry version.
    head = constraint.split("#", 1)[0]
    return "/" in head and not head[0].isdigit()


def parse_manifest(repo_root: Path, manifest: str, **kwargs) -> list[Dependency]:
    """Dispatch to the right parser based on the manifest filename."""
    path = repo_root / manifest
    suffix = path.suffix.lower()
    if suffix == ".toml":
        return parse_pyproject(path, include_optional=kwargs.get("include_optional", False))
    if suffix == ".json":
        return parse_package_json(path, include_dev=kwargs.get("include_dev", True))
    raise ValueError(f"Unsupported manifest type: {manifest}")
