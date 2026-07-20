"""What the daemon and its clients need to talk about an engine.

The engine itself is `engines/whisper_local.py`, which documents each
method where it is implemented. A second engine would be a second
module using these same types.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class EngineError(Exception):
    """Transcription cannot work; the message says why."""


class EnginePhase(enum.Enum):
    """What the engine is doing, as a fact rather than a sentence."""

    NOT_LOADED = "not loaded"
    DOWNLOADING = "downloading"
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class EngineStatus:
    """The engine's state, in a form callers can ask questions of.

    This used to be a free-text string ("downloading 42%") that the tray
    and the daemon took apart again with startswith/removeprefix to
    recover the phase and the percentage. Changing the wording silently
    broke both, and no test could catch it. Callers now compare phases
    and read `percent`; the wording is written where it is displayed.
    """

    phase: EnginePhase
    percent: int = 0
    error: str = ""

    @property
    def busy(self) -> bool:
        """The engine is on its way to being usable, but is not yet."""
        return self.phase in (EnginePhase.DOWNLOADING, EnginePhase.LOADING)

    def describe(self) -> str:
        """A short neutral phrase for logs, notifications and the CLI.

        Not for the tray: it builds a richer label from the phase itself.
        """
        if self.phase is EnginePhase.DOWNLOADING:
            return f"downloading {self.percent}%"
        if self.phase is EnginePhase.FAILED:
            return f"error: {self.error}"
        return self.phase.value
