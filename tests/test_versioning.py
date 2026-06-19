from dep_automation.models import Ecosystem, UpdateKind
from dep_automation.versioning import (
    SemVer,
    anchor,
    classify_update,
    compare,
    npm_anchor,
    npm_satisfies,
    pypi_anchor,
    pypi_satisfies,
    semver_compare,
)

PYPI = Ecosystem.PYPI
NPM = Ecosystem.NPM


class TestPypi:
    def test_anchor_prefers_pin(self):
        assert pypi_anchor("==1.2.3") == "1.2.3"

    def test_anchor_uses_highest_lower_bound(self):
        assert pypi_anchor(">=2.1.4, <2.4") == "2.1.4"

    def test_anchor_compound(self):
        assert pypi_anchor(">=5.3.6, <6.0.0") == "5.3.6"

    def test_anchor_invalid(self):
        assert pypi_anchor("not-a-spec ===") is None

    def test_satisfies_in_range(self):
        assert pypi_satisfies("2.3.0", ">=2.1.4, <2.4")

    def test_satisfies_out_of_range(self):
        assert not pypi_satisfies("2.5.0", ">=2.1.4, <2.4")

    def test_satisfies_excludes_prerelease(self):
        assert not pypi_satisfies("2.5.0rc1", ">=2.0")

    def test_empty_constraint_allows_anything(self):
        assert pypi_satisfies("9.9.9", "")

    def test_compare(self):
        assert compare(PYPI, "1.2.0", "1.10.0") < 0
        assert compare(PYPI, "2.0.0", "2.0.0") == 0


class TestSemver:
    def test_parse_basic(self):
        sv = SemVer.parse("1.2.3")
        assert (sv.major, sv.minor, sv.patch) == (1, 2, 3)

    def test_parse_with_v_prefix_and_prerelease(self):
        sv = SemVer.parse("v1.2.3-beta.1")
        assert sv.prerelease == "beta.1"

    def test_compare_numeric_not_lexical(self):
        assert semver_compare("1.9.0", "1.10.0") < 0

    def test_compare_prerelease_lower_than_release(self):
        assert semver_compare("1.0.0-rc.1", "1.0.0") < 0

    def test_caret_satisfies(self):
        assert npm_satisfies("7.3.0", "^7.1.2")
        assert not npm_satisfies("8.0.0", "^7.1.2")

    def test_caret_zero_major(self):
        # ^0.2.3 := >=0.2.3 <0.3.0
        assert npm_satisfies("0.2.9", "^0.2.3")
        assert not npm_satisfies("0.3.0", "^0.2.3")

    def test_tilde_satisfies(self):
        assert npm_satisfies("9.2.9", "~9.2.5")
        assert not npm_satisfies("9.3.0", "~9.2.5")

    def test_exact(self):
        assert npm_satisfies("1.2.3", "1.2.3")
        assert not npm_satisfies("1.2.4", "1.2.3")

    def test_range_compound(self):
        assert npm_satisfies("2.5.0", ">=2.0.0 <3.0.0")
        assert not npm_satisfies("3.0.0", ">=2.0.0 <3.0.0")

    def test_or_alternatives(self):
        assert npm_satisfies("1.5.0", "^1.0.0 || ^2.0.0")
        assert npm_satisfies("2.5.0", "^1.0.0 || ^2.0.0")
        assert not npm_satisfies("3.0.0", "^1.0.0 || ^2.0.0")

    def test_x_range(self):
        assert npm_satisfies("1.4.7", "1.x")
        assert not npm_satisfies("2.0.0", "1.x")

    def test_wildcard_star(self):
        assert npm_satisfies("99.0.0", "*")

    def test_hyphen_range(self):
        assert npm_satisfies("1.5.0", "1.2.0 - 1.8.0")
        assert not npm_satisfies("1.9.0", "1.2.0 - 1.8.0")

    def test_prerelease_excluded_by_default(self):
        assert not npm_satisfies("2.0.0-beta.1", "^1.0.0")

    def test_anchor(self):
        assert npm_anchor("^7.1.2") == "7.1.2"
        assert npm_anchor("~9.2.5") == "9.2.5"
        assert npm_anchor(">=2.0.0 <3.0.0") == "2.0.0"


class TestClassify:
    def test_major(self):
        assert classify_update(PYPI, "1.2.3", "2.0.0") is UpdateKind.MAJOR

    def test_minor(self):
        assert classify_update(NPM, "1.2.3", "1.3.0") is UpdateKind.MINOR

    def test_patch(self):
        assert classify_update(NPM, "1.2.3", "1.2.4") is UpdateKind.PATCH

    def test_unknown_without_current(self):
        assert classify_update(PYPI, None, "1.0.0") is UpdateKind.UNKNOWN


def test_anchor_facade_dispatch():
    assert anchor(PYPI, ">=1.0") == "1.0"
    assert anchor(NPM, "^2.3.4") == "2.3.4"
