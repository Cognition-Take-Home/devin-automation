from dep_automation.config import Config
from dep_automation.models import Dependency, Ecosystem
from dep_automation.usage import UsageScanner, search_patterns


def _dep(name, eco=Ecosystem.PYPI):
    return Dependency(name=name, ecosystem=eco, constraint="*", manifest="m")


def test_search_patterns_pypi_normalises_separators():
    pats = search_patterns(_dep("flask-appbuilder"))
    joined = pats[0]
    assert "flask_appbuilder" in joined
    assert r"flask\.appbuilder" in joined  # the dot is regex-escaped
    assert joined.startswith(r"\b")


def test_search_patterns_npm_anchors_import_specifier():
    pats = search_patterns(_dep("ol", Ecosystem.NPM))
    # matches '<name>' or "<name>/..." but not the substring inside another word
    assert pats == [r"""['"]ol(?:['"/])"""]


def test_scanner_sums_per_file_counts_and_passes_paths():
    captured = {}

    def runner(patterns, paths, cwd):
        captured["patterns"] = patterns
        captured["paths"] = paths
        captured["cwd"] = cwd
        return "superset/a.py:3\nsuperset/b.py:5\n"

    cfg = Config(
        target_repo="a/b",
        target_repo_path="/repo",
        usage_paths={"pypi": ["superset"]},
    )
    scanner = UsageScanner(cfg, runner=runner)
    assert scanner.count(_dep("sqlalchemy")) == 8
    assert captured["paths"] == ["superset"]
    assert captured["cwd"] == "/repo"


def test_scanner_handles_no_matches():
    cfg = Config(target_repo="a/b", target_repo_path="/repo")
    scanner = UsageScanner(cfg, runner=lambda *a: "")
    assert scanner.count(_dep("unused")) == 0


def test_scanner_counts_maps_keys():
    cfg = Config(target_repo="a/b", target_repo_path="/repo")
    scanner = UsageScanner(cfg, runner=lambda *a: "x:2\n")
    counts = scanner.counts([_dep("Flask"), _dep("react", Ecosystem.NPM)])
    assert counts == {("pypi", "flask"): 2, ("npm", "react"): 2}
