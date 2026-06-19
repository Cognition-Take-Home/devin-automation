from pathlib import Path

from dep_automation.manifests import parse_package_json, parse_pyproject
from dep_automation.models import Ecosystem

FIX = Path(__file__).parent / "fixtures"


class TestPyproject:
    def test_parses_top_level(self):
        deps = parse_pyproject(FIX / "sample_pyproject.toml")
        names = {d.name for d in deps}
        assert names == {"celery", "click", "colorama", "pandas", "gunicorn"}
        assert all(d.ecosystem is Ecosystem.PYPI for d in deps)

    def test_strips_extras_and_markers(self):
        deps = {d.name: d for d in parse_pyproject(FIX / "sample_pyproject.toml")}
        assert deps["pandas"].constraint == ">=2.1.4, <2.4"
        # environment marker is stripped from the constraint
        assert deps["gunicorn"].constraint == ">=25.3.0, <26"

    def test_anchor_populated(self):
        deps = {d.name: d for d in parse_pyproject(FIX / "sample_pyproject.toml")}
        assert deps["celery"].current_version == "5.3.6"
        assert deps["colorama"].current_version is None

    def test_optional_excluded_by_default(self):
        deps = {d.name for d in parse_pyproject(FIX / "sample_pyproject.toml")}
        assert "pyathena" not in deps

    def test_optional_included_when_requested(self):
        parsed = parse_pyproject(FIX / "sample_pyproject.toml", include_optional=True)
        assert "pyathena" in {d.name for d in parsed}


class TestPackageJson:
    def test_skips_non_registry(self):
        deps = {d.name for d in parse_package_json(FIX / "sample_package.json")}
        assert "@apache-superset/core" not in deps  # file:
        assert "some-fork" not in deps  # github:

    def test_parses_registry_deps(self):
        deps = {d.name: d for d in parse_package_json(FIX / "sample_package.json")}
        assert deps["@braintree/sanitize-url"].constraint == "^7.1.2"
        assert deps["@braintree/sanitize-url"].current_version == "7.1.2"
        assert deps["react"].current_version == "18.3.1"

    def test_dev_dependencies_included(self):
        deps = {d.name for d in parse_package_json(FIX / "sample_package.json")}
        assert "typescript" in deps
        assert "eslint" in deps

    def test_dev_dependencies_excluded(self):
        deps = {d.name for d in parse_package_json(FIX / "sample_package.json", include_dev=False)}
        assert "typescript" not in deps
