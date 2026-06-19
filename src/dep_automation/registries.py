"""Look up the latest published version of a package on PyPI or npm.

Uses only the standard library so the automation has no runtime HTTP dependency.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

from .models import Ecosystem
from .versioning import compare, is_prerelease, is_valid

PYPI_BASE = "https://pypi.org/pypi"
NPM_BASE = "https://registry.npmjs.org"
USER_AGENT = "devin-dependency-automation/0.1 (+https://github.com/Cognition-Take-Home)"


class RegistryError(RuntimeError):
    """Raised when a registry lookup fails (network or missing package)."""


class HttpFetcher(Protocol):
    """Fetches a URL and returns decoded JSON. Injected to enable testing."""

    def __call__(self, url: str) -> dict: ...


def _default_fetch(url: str) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RegistryError(f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Failed to fetch {url}: {exc}") from exc


class RegistryClient:
    """Resolves latest versions, allowing or excluding pre-releases."""

    def __init__(self, fetch: HttpFetcher | None = None, *, allow_prerelease: bool = False):
        self._fetch = fetch or _default_fetch
        self.allow_prerelease = allow_prerelease

    def latest_version(self, ecosystem: Ecosystem, name: str) -> str:
        if ecosystem is Ecosystem.PYPI:
            return self._latest_pypi(name)
        return self._latest_npm(name)

    def _latest_pypi(self, name: str) -> str:
        url = f"{PYPI_BASE}/{urllib.parse.quote(name)}/json"
        data = self._fetch(url)
        releases = data.get("releases", {})
        candidates = [
            ver
            for ver, files in releases.items()
            if files  # skip yanked / empty releases
            and is_valid(Ecosystem.PYPI, ver)  # skip non-PEP440 versions
            and (self.allow_prerelease or not is_prerelease(Ecosystem.PYPI, ver))
        ]
        if not candidates:
            # Fall back to whatever the index reports as the info version.
            info_version = data.get("info", {}).get("version")
            if info_version:
                return info_version
            raise RegistryError(f"No published versions found for {name} on PyPI")
        return max(candidates, key=lambda v: _CmpKey(Ecosystem.PYPI, v))

    def _latest_npm(self, name: str) -> str:
        url = f"{NPM_BASE}/{_npm_quote(name)}"
        data = self._fetch(url)
        dist_tags = data.get("dist-tags", {})
        if not self.allow_prerelease and dist_tags.get("latest"):
            return dist_tags["latest"]
        versions = list(data.get("versions", {}).keys())
        candidates = [
            v
            for v in versions
            if is_valid(Ecosystem.NPM, v)
            and (self.allow_prerelease or not is_prerelease(Ecosystem.NPM, v))
        ]
        if not candidates:
            if dist_tags.get("latest"):
                return dist_tags["latest"]
            raise RegistryError(f"No published versions found for {name} on npm")
        return max(candidates, key=lambda v: _CmpKey(Ecosystem.NPM, v))


def _npm_quote(name: str) -> str:
    """Scoped packages (@scope/name) keep the slash but escape the @."""
    if name.startswith("@"):
        scope, _, pkg = name[1:].partition("/")
        return f"@{urllib.parse.quote(scope)}%2f{urllib.parse.quote(pkg)}"
    return urllib.parse.quote(name)


class _CmpKey:
    """Adapter so ``max`` can order versions via the ecosystem comparator."""

    __slots__ = ("ecosystem", "version")

    def __init__(self, ecosystem: Ecosystem, version: str):
        self.ecosystem = ecosystem
        self.version = version

    def __lt__(self, other: _CmpKey) -> bool:
        return compare(self.ecosystem, self.version, other.version) < 0
