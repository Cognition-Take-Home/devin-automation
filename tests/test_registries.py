import pytest

from dep_automation.models import Ecosystem
from dep_automation.registries import RegistryClient, RegistryError


def make_pypi(versions, info_version="0.0.0"):
    return {
        "info": {"version": info_version},
        "releases": {v: [{"filename": f"{v}.tar.gz"}] for v in versions},
    }


def make_npm(latest, versions):
    return {
        "dist-tags": {"latest": latest},
        "versions": {v: {} for v in versions},
    }


class TestPypiLatest:
    def test_picks_highest_stable(self):
        data = make_pypi(["1.0.0", "1.10.0", "1.2.0"])
        client = RegistryClient(fetch=lambda url: data)
        assert client.latest_version(Ecosystem.PYPI, "pkg") == "1.10.0"

    def test_excludes_prerelease(self):
        data = make_pypi(["1.0.0", "2.0.0rc1"])
        client = RegistryClient(fetch=lambda url: data)
        assert client.latest_version(Ecosystem.PYPI, "pkg") == "1.0.0"

    def test_includes_prerelease_when_allowed(self):
        data = make_pypi(["1.0.0", "2.0.0rc1"])
        client = RegistryClient(fetch=lambda url: data, allow_prerelease=True)
        assert client.latest_version(Ecosystem.PYPI, "pkg") == "2.0.0rc1"

    def test_skips_yanked_empty_releases(self):
        data = make_pypi(["1.0.0"])
        data["releases"]["1.5.0"] = []  # yanked / no files
        client = RegistryClient(fetch=lambda url: data)
        assert client.latest_version(Ecosystem.PYPI, "pkg") == "1.0.0"


class TestNpmLatest:
    def test_uses_dist_tag_latest(self):
        data = make_npm("9.2.5", ["9.2.5", "9.3.0-beta.1"])
        client = RegistryClient(fetch=lambda url: data)
        assert client.latest_version(Ecosystem.NPM, "pkg") == "9.2.5"

    def test_scoped_package_url(self):
        captured = {}

        def fetch(url):
            captured["url"] = url
            return make_npm("1.0.0", ["1.0.0"])

        client = RegistryClient(fetch=fetch)
        client.latest_version(Ecosystem.NPM, "@scope/pkg")
        assert "@scope%2fpkg" in captured["url"]

    def test_allow_prerelease_scans_versions(self):
        data = make_npm("9.2.5", ["9.2.5", "9.3.0-beta.1"])
        client = RegistryClient(fetch=lambda url: data, allow_prerelease=True)
        assert client.latest_version(Ecosystem.NPM, "pkg") == "9.3.0-beta.1"


def test_registry_error_propagates():
    def fetch(url):
        raise RegistryError("boom")

    client = RegistryClient(fetch=fetch)
    with pytest.raises(RegistryError):
        client.latest_version(Ecosystem.PYPI, "pkg")
