"""What every desktop module shares.

The desktop backend itself is `desktop/x11.py` — the module boundary is
the seam, and each method documents its own contract there. There is no
separate interface declaration: one implementation does not need two
descriptions of itself that can disagree.
"""

from __future__ import annotations


class DesktopError(Exception):
    """A desktop operation failed; the message says why and how to fix it."""
