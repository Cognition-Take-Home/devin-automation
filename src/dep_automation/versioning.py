"""Version-constraint parsing and comparison for PyPI and npm.

The two ecosystems use different grammars:

* PyPI constraints are PEP 440 specifiers, handled by the ``packaging`` library.
* npm constraints are semver ranges, handled by the small ``semver`` helpers below.

Each ecosystem exposes the same three questions the runner cares about:

* ``anchor(constraint)`` -> a representative "current" version string (or ``None``).
* ``satisfies(version, constraint)`` -> is ``version`` permitted by the constraint?
* ``compare(a, b)`` -> -1/0/1 ordering of two concrete versions.
"""

from __future__ import annotations

import re

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .models import Ecosystem, UpdateKind

# ---------------------------------------------------------------------------
# PyPI (PEP 440)
# ---------------------------------------------------------------------------


def pypi_anchor(constraint: str) -> str | None:
    """Return a representative current version for a PEP 440 specifier.

    Prefers an exact pin (``==``), then the highest lower bound (``>=``/``>``/``~=``),
    falling back to the highest version mentioned by any clause.
    """
    try:
        spec = SpecifierSet(constraint)
    except InvalidSpecifier:
        return None

    pinned: list[Version] = []
    lower: list[Version] = []
    other: list[Version] = []
    for clause in spec:
        try:
            ver = Version(clause.version.replace(".*", ""))
        except InvalidVersion:
            continue
        if clause.operator in ("==", "==="):
            pinned.append(ver)
        elif clause.operator in (">=", ">", "~="):
            lower.append(ver)
        else:
            other.append(ver)

    for bucket in (pinned, lower, other):
        if bucket:
            return str(max(bucket))
    return None


def pypi_satisfies(version: str, constraint: str) -> bool:
    if not constraint:
        return True
    try:
        spec = SpecifierSet(constraint)
        return spec.contains(version, prereleases=False)
    except (InvalidSpecifier, InvalidVersion):
        return False


def pypi_is_prerelease(version: str) -> bool:
    try:
        return Version(version).is_prerelease
    except InvalidVersion:
        return False


def pypi_is_valid(version: str) -> bool:
    try:
        Version(version)
        return True
    except InvalidVersion:
        return False


def pypi_compare(a: str, b: str) -> int:
    va, vb = Version(a), Version(b)
    return (va > vb) - (va < vb)


# ---------------------------------------------------------------------------
# npm (semver) - a deliberately small but correct subset
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


class SemVer:
    """A parsed semantic version (build metadata ignored for ordering)."""

    __slots__ = ("major", "minor", "patch", "prerelease")

    def __init__(self, major: int, minor: int, patch: int, prerelease: str | None):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.prerelease = prerelease

    @classmethod
    def parse(cls, raw: str) -> SemVer | None:
        m = _SEMVER_RE.match(raw.strip())
        if not m:
            return None
        return cls(int(m[1]), int(m[2]), int(m[3]), m[4])

    @property
    def is_prerelease(self) -> bool:
        return self.prerelease is not None

    def _key(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._key() == other._key() and self.prerelease == other.prerelease

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.prerelease}" if self.prerelease else base


def _cmp_prerelease(a: str | None, b: str | None) -> int:
    """Compare prerelease tags per semver rules. No tag outranks any tag."""
    if a == b:
        return 0
    if a is None:
        return 1  # release > prerelease
    if b is None:
        return -1
    a_parts, b_parts = a.split("."), b.split(".")
    for ap, bp in zip(a_parts, b_parts, strict=False):
        a_num, b_num = ap.isdigit(), bp.isdigit()
        if a_num and b_num:
            if int(ap) != int(bp):
                return -1 if int(ap) < int(bp) else 1
        elif a_num != b_num:
            return -1 if a_num else 1  # numeric identifiers are lower
        elif ap != bp:
            return -1 if ap < bp else 1
    return (len(a_parts) > len(b_parts)) - (len(a_parts) < len(b_parts))


def semver_compare(a: str, b: str) -> int:
    pa, pb = SemVer.parse(a), SemVer.parse(b)
    if pa is None or pb is None:
        return (a > b) - (a < b)
    if pa._key() != pb._key():
        return -1 if pa._key() < pb._key() else 1
    return _cmp_prerelease(pa.prerelease, pb.prerelease)


# A semver range is one or more comma/space separated comparators, optionally split
# into alternatives by "||". Each comparator is parsed to an (op, SemVer) pair.
_COMPARATOR_RE = re.compile(r"(>=|<=|>|<|=|\^|~)?\s*(.+)")


def _expand_xrange(token: str) -> str:
    """Replace ``x``/``X``/``*`` placeholders so a token becomes a real version."""
    return re.sub(r"[xX*]", "0", token)


def _normalise_to_semver(raw: str) -> SemVer | None:
    """Parse a (possibly partial / wildcard) version token into a full SemVer triple."""
    expanded = _expand_xrange(raw)
    sv = SemVer.parse(expanded)
    if sv is not None:
        return sv
    nums = expanded.split(".")
    if not nums or not nums[0].isdigit():
        return None
    while len(nums) < 3:
        nums.append("0")
    try:
        return SemVer(int(nums[0]), int(nums[1]), int(nums[2]), None)
    except ValueError:
        return None


def _parse_comparator(token: str) -> list[tuple[str, SemVer]]:
    token = token.strip()
    if not token or token in ("*", "x", "X", "latest"):
        return [(">=", SemVer(0, 0, 0, None))]
    m = _COMPARATOR_RE.match(token)
    if not m:
        return []
    op, raw = m[1] or "=", m[2].strip()

    has_wildcard = bool(re.search(r"[xX*]", raw))
    sv = _normalise_to_semver(raw)
    if sv is None:
        return []

    if op == "^":
        return _caret(sv)
    if op == "~":
        return _tilde(sv)
    if op in (">=", "<=", ">", "<"):
        return [(op, sv)]
    # Bare version: an x-range expands to a >=/< window, otherwise an exact match.
    if has_wildcard:
        return _xrange_window(raw)
    return [("=", sv)]


def _caret(sv: SemVer) -> list[tuple[str, SemVer]]:
    if sv.major > 0:
        upper = SemVer(sv.major + 1, 0, 0, None)
    elif sv.minor > 0:
        upper = SemVer(0, sv.minor + 1, 0, None)
    else:
        upper = SemVer(0, 0, sv.patch + 1, None)
    return [(">=", sv), ("<", upper)]


def _tilde(sv: SemVer) -> list[tuple[str, SemVer]]:
    upper = SemVer(sv.major, sv.minor + 1, 0, None)
    return [(">=", sv), ("<", upper)]


def _xrange_window(raw: str) -> list[tuple[str, SemVer]]:
    parts = raw.split(".")
    if parts and parts[0] not in ("x", "X", "*"):
        major = int(parts[0])
        if len(parts) >= 2 and parts[1] not in ("x", "X", "*"):
            minor = int(parts[1])
            return [(">=", SemVer(major, minor, 0, None)), ("<", SemVer(major, minor + 1, 0, None))]
        return [(">=", SemVer(major, 0, 0, None)), ("<", SemVer(major + 1, 0, 0, None))]
    return [(">=", SemVer(0, 0, 0, None))]


def _parse_range(constraint: str) -> list[list[tuple[str, SemVer]]]:
    """Parse a range into a disjunction (OR) of conjunctions (AND) of comparators."""
    alternatives: list[list[tuple[str, SemVer]]] = []
    for alt in constraint.split("||"):
        comparators: list[tuple[str, SemVer]] = []
        # Hyphen range "a - b" -> ">=a <=b".
        hyphen = re.match(r"^\s*(\S+)\s+-\s+(\S+)\s*$", alt)
        if hyphen:
            lo = SemVer.parse(_expand_xrange(hyphen[1]))
            hi = SemVer.parse(_expand_xrange(hyphen[2]))
            if lo and hi:
                comparators = [(">=", lo), ("<=", hi)]
            alternatives.append(comparators)
            continue
        for token in alt.replace(",", " ").split():
            comparators.extend(_parse_comparator(token))
        alternatives.append(comparators)
    return alternatives


def _satisfies_comparators(version: SemVer, comparators: list[tuple[str, SemVer]]) -> bool:
    for op, ref in comparators:
        c = semver_compare(str(version), str(ref))
        if op == ">=" and not c >= 0:
            return False
        if op == ">" and not c > 0:
            return False
        if op == "<=" and not c <= 0:
            return False
        if op == "<" and not c < 0:
            return False
        if op == "=" and c != 0:
            return False
    return True


def npm_satisfies(version: str, constraint: str) -> bool:
    sv = SemVer.parse(version)
    if sv is None:
        return False
    # By default a pre-release only satisfies a range that explicitly references one.
    if sv.is_prerelease and "-" not in constraint:
        return False
    for comparators in _parse_range(constraint):
        if comparators and _satisfies_comparators(sv, comparators):
            return True
    return False


def npm_anchor(constraint: str) -> str | None:
    """Highest concrete version mentioned by the range (its lower-bound anchor)."""
    best: SemVer | None = None
    for comparators in _parse_range(constraint):
        for op, ref in comparators:
            if op in (">=", "=", ">", "<=", "~", "^"):
                if best is None or semver_compare(str(ref), str(best)) > 0:
                    best = ref
    return str(best) if best else None


def npm_is_prerelease(version: str) -> bool:
    sv = SemVer.parse(version)
    return bool(sv and sv.is_prerelease)


def npm_is_valid(version: str) -> bool:
    return SemVer.parse(version) is not None


# ---------------------------------------------------------------------------
# Ecosystem-agnostic façade
# ---------------------------------------------------------------------------


def anchor(ecosystem: Ecosystem, constraint: str) -> str | None:
    return pypi_anchor(constraint) if ecosystem is Ecosystem.PYPI else npm_anchor(constraint)


def satisfies(ecosystem: Ecosystem, version: str, constraint: str) -> bool:
    if ecosystem is Ecosystem.PYPI:
        return pypi_satisfies(version, constraint)
    return npm_satisfies(version, constraint)


def is_prerelease(ecosystem: Ecosystem, version: str) -> bool:
    if ecosystem is Ecosystem.PYPI:
        return pypi_is_prerelease(version)
    return npm_is_prerelease(version)


def is_valid(ecosystem: Ecosystem, version: str) -> bool:
    if ecosystem is Ecosystem.PYPI:
        return pypi_is_valid(version)
    return npm_is_valid(version)


def compare(ecosystem: Ecosystem, a: str, b: str) -> int:
    if ecosystem is Ecosystem.PYPI:
        return pypi_compare(a, b)
    return semver_compare(a, b)


def classify_update(ecosystem: Ecosystem, current: str | None, latest: str) -> UpdateKind:
    """Classify the jump from ``current`` to ``latest`` as major/minor/patch."""
    if not current:
        return UpdateKind.UNKNOWN
    try:
        if ecosystem is Ecosystem.PYPI:
            cur, new = Version(current), Version(latest)
            cur_t = (cur.release + (0, 0, 0))[:3]
            new_t = (new.release + (0, 0, 0))[:3]
        else:
            csv, nsv = SemVer.parse(current), SemVer.parse(latest)
            if not csv or not nsv:
                return UpdateKind.UNKNOWN
            cur_t = (csv.major, csv.minor, csv.patch)
            new_t = (nsv.major, nsv.minor, nsv.patch)
    except (InvalidVersion, ValueError):
        return UpdateKind.UNKNOWN

    if new_t[0] != cur_t[0]:
        return UpdateKind.MAJOR
    if new_t[1] != cur_t[1]:
        return UpdateKind.MINOR
    if new_t[2] != cur_t[2]:
        return UpdateKind.PATCH
    return UpdateKind.UNKNOWN
