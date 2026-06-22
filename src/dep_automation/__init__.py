"""Library usage-optimization automation driven by the Devin API.

Each run enumerates a target repository's *top-level* dependencies, cheaply ranks them
by how heavily the repo uses them (and how recently each was looked at), and hands a
short candidate list to a single Devin session. Devin picks one library, studies how the
repo uses it versus its official documentation, and makes small, safe improvements to
that usage — or opens no PR if nothing is worthwhile. It is explicitly *not* a version
bumper.
"""

__version__ = "0.2.0"
