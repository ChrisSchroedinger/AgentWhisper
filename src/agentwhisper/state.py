"""Recording state machine — pure logic, no I/O, no threads, no clocks.

The daemon feeds events in (key presses/releases, timer expiries,
transcription results) and executes the actions that come back out
(start/stop recording, schedule/cancel the debounce timer). Because
time is an event here rather than something we measure, every timing
edge case — X11 auto-repeat above all — is unit-testable.

X11 auto-repeat background: holding a key makes X emit synthetic
release+press pairs at the keyboard repeat rate (~30ms apart). A real
release is only "real" if no press follows within the debounce window.
The daemon implements SCHEDULE_SETTLE with a timer that then feeds
release_settled() back in; a press in the meantime emits CANCEL_SETTLE.
"""

from __future__ import annotations

from enum import Enum, auto

RELEASE_DEBOUNCE_SECONDS = 0.18


class Phase(Enum):
    IDLE = auto()
    RECORDING = auto()
    TRANSCRIBING = auto()


class Action(Enum):
    START_RECORDING = auto()
    STOP_RECORDING = auto()   # stop capture and begin transcription
    ABORT_RECORDING = auto()  # stop capture and discard (disable/shutdown)
    SCHEDULE_SETTLE = auto()  # start the debounce timer
    CANCEL_SETTLE = auto()    # press arrived: the release was auto-repeat


class DictationStateMachine:
    """Tracks hotkey/recording state; returns the actions to perform.

    mode = "hold":   press starts recording, settled release stops it.
    mode = "toggle": first (non-repeat) press starts, next press stops;
                     releases only matter for tracking auto-repeat.
    """

    def __init__(self, mode: str = "hold", enabled: bool = True):
        if mode not in ("hold", "toggle"):
            raise ValueError(f"unknown mode {mode!r}")
        self.mode = mode
        self.enabled = enabled
        self.phase = Phase.IDLE
        self._key_held = False      # physical key state as best we know
        self._settle_pending = False

    # -- hotkey events -------------------------------------------------

    def key_pressed(self) -> list[Action]:
        actions: list[Action] = []
        if self._settle_pending:
            # A press right after a release is X11 auto-repeat noise.
            self._settle_pending = False
            actions.append(Action.CANCEL_SETTLE)
            self._key_held = True
            return actions

        if self._key_held:
            return actions  # repeat press with no release seen; ignore
        self._key_held = True

        if not self.enabled:
            return actions

        if self.mode == "hold":
            if self.phase is Phase.IDLE:
                self.phase = Phase.RECORDING
                actions.append(Action.START_RECORDING)
        else:  # toggle
            if self.phase is Phase.IDLE:
                self.phase = Phase.RECORDING
                actions.append(Action.START_RECORDING)
            elif self.phase is Phase.RECORDING:
                self.phase = Phase.TRANSCRIBING
                actions.append(Action.STOP_RECORDING)
        return actions

    def key_released(self) -> list[Action]:
        if not self._key_held:
            return []
        self._settle_pending = True
        return [Action.SCHEDULE_SETTLE]

    def release_settled(self) -> list[Action]:
        """The debounce timer fired: the release was real."""
        if not self._settle_pending:
            return []  # timer raced with a cancel; treat as cancelled
        self._settle_pending = False
        self._key_held = False

        if self.mode == "hold" and self.phase is Phase.RECORDING:
            self.phase = Phase.TRANSCRIBING
            return [Action.STOP_RECORDING]
        return []

    # -- other events ---------------------------------------------------

    def cancel_requested(self) -> list[Action]:
        """The cancel key (Escape): discard an active recording.

        In hold mode the hotkey is usually still physically held when
        this fires; its eventual release settles in IDLE and does
        nothing — no transcription sneaks in behind the cancel.
        """
        if self.phase is Phase.RECORDING:
            self.phase = Phase.IDLE
            return [Action.ABORT_RECORDING]
        return []

    def max_duration_reached(self) -> list[Action]:
        if self.phase is Phase.RECORDING:
            self.phase = Phase.TRANSCRIBING
            return [Action.STOP_RECORDING]
        return []

    def transcription_finished(self) -> list[Action]:
        if self.phase is Phase.TRANSCRIBING:
            self.phase = Phase.IDLE
        return []

    def set_enabled(self, enabled: bool) -> list[Action]:
        self.enabled = enabled
        if not enabled and self.phase is Phase.RECORDING:
            self.phase = Phase.IDLE
            return [Action.ABORT_RECORDING]
        return []

    def set_mode(self, mode: str) -> list[Action]:
        """Switch hold/toggle; an active recording is aborted, not kept."""
        if mode not in ("hold", "toggle"):
            raise ValueError(f"unknown mode {mode!r}")
        actions: list[Action] = []
        if mode != self.mode and self.phase is Phase.RECORDING:
            self.phase = Phase.IDLE
            actions.append(Action.ABORT_RECORDING)
        self.mode = mode
        return actions

    def shutdown(self) -> list[Action]:
        if self.phase is Phase.RECORDING:
            self.phase = Phase.IDLE
            return [Action.ABORT_RECORDING]
        return []
