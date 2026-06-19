"""Dependency-management automation that drives Devin to perform research-led upgrades.

This package inspects the *top-level* dependencies of a target repository, compares
each one against the latest version published on its registry (PyPI / npm), and, for
dependencies that need a manifest change to adopt the new release, opens a Devin
session instructed to research the changes between versions and adopt improvements
*without forcing* breaking changes.
"""

__version__ = "0.1.0"
