from dep_automation.models import Dependency, Ecosystem
from dep_automation.selection import select_candidates


def _dep(name, eco=Ecosystem.PYPI):
    return Dependency(name=name, ecosystem=eco, constraint="*", manifest="m")


def _usage(**kw):
    return {("pypi", k.lower()): v for k, v in kw.items()}


def test_ranks_by_usage_desc():
    deps = [_dep("a"), _dep("b"), _dep("c")]
    usage = _usage(a=5, b=50, c=10)
    picked = select_candidates(deps, usage, set(), shortlist_size=2)
    assert [c.name for c in picked] == ["b", "c"]
    assert picked[0].usage == 50


def test_excludes_recently_considered():
    deps = [_dep("a"), _dep("b"), _dep("c")]
    usage = _usage(a=5, b=50, c=10)
    picked = select_candidates(deps, usage, {("pypi", "b")}, shortlist_size=5)
    assert [c.name for c in picked] == ["c", "a"]


def test_relaxes_cooldown_when_everything_excluded():
    deps = [_dep("a"), _dep("b")]
    usage = _usage(a=5, b=9)
    recently = {("pypi", "a"), ("pypi", "b")}
    picked = select_candidates(deps, usage, recently, shortlist_size=5)
    # all in cooldown -> rotation wrapped, fall back to the full set
    assert {c.name for c in picked} == {"a", "b"}


def test_alphabetical_tiebreak():
    deps = [_dep("zlib"), _dep("alpha")]
    usage = _usage(zlib=7, alpha=7)
    picked = select_candidates(deps, usage, set(), shortlist_size=5)
    assert [c.name for c in picked] == ["alpha", "zlib"]


def test_unknown_usage_treated_as_zero():
    deps = [_dep("a"), _dep("b")]
    picked = select_candidates(deps, {("pypi", "a"): 3}, set(), shortlist_size=5)
    assert picked[0].name == "a"
    assert picked[1].usage == 0
