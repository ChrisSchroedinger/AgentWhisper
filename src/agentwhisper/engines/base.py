"""The Engine contract every speech-to-text backend implements.

Future engines (cloud STT, an LLM 'agent mode' engine) drop in behind
this interface without the daemon changing.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol

import numpy as np


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


class Engine(Protocol):
    @property
    def status(self) -> EngineStatus:
        """What the engine is doing right now."""
        ...

    @property
    def load_finished(self) -> bool:
        """True once load() has returned, in success or failure."""
        ...

    @property
    def downloaded(self) -> bool:
        """True if the last load() had to fetch the model first."""
        ...

    def is_cached(self) -> bool:
        """True if the model is available locally, so load() will not
        need the network."""
        ...

    def load(self) -> None:
        """Blocking: acquire the model. Called once, from a background
        thread, at daemon startup. Errors are reflected in status."""
        ...

    def warm_up(self) -> None:
        """Blocking: make the engine ready to transcribe.

        Called from a background thread when recording starts, so an
        engine that releases resources while idle can reacquire them
        while the user is still speaking. A no-op is a valid
        implementation; transcribe() must work either way.
        """
        ...

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        """Mono int16 samples → text. Blocks; waits for load() if needed.
        Returns '' when no speech is detected. Raises EngineError."""
        ...
