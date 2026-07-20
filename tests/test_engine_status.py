"""The engine reports its state as a value, not a sentence.

These are the tests the old free-text status made impossible: the tray
and the daemon each parsed the string with startswith/removeprefix, and
nothing checked that what they parsed was what the engine emitted.
"""

import dataclasses

import pytest
from tests.helpers import make_settings
from tests.test_daemon import _FakeDesktop

from agentwhisper.daemon import Daemon
from agentwhisper.engines.base import EnginePhase, EngineStatus
from agentwhisper.tray import status_label


class TestEngineStatus:
    def test_busy_covers_the_states_that_are_not_usable_yet(self):
        assert EngineStatus(EnginePhase.DOWNLOADING, percent=42).busy
        assert EngineStatus(EnginePhase.LOADING).busy
        assert not EngineStatus(EnginePhase.READY).busy
        assert not EngineStatus(EnginePhase.FAILED, error="boom").busy
        assert not EngineStatus(EnginePhase.NOT_LOADED).busy

    @pytest.mark.parametrize("status, expected", [
        (EngineStatus(EnginePhase.NOT_LOADED), "not loaded"),
        (EngineStatus(EnginePhase.LOADING), "loading"),
        (EngineStatus(EnginePhase.READY), "ready"),
        (EngineStatus(EnginePhase.DOWNLOADING, percent=42), "downloading 42%"),
        (EngineStatus(EnginePhase.FAILED, error="no disk space"),
         "error: no disk space"),
    ])
    def test_describe(self, status, expected):
        assert status.describe() == expected

    def test_status_is_immutable(self):
        """Callers pass it around freely; nobody should be able to edit
        the engine's state through a copy of its status."""
        status = EngineStatus(EnginePhase.READY)
        with pytest.raises(dataclasses.FrozenInstanceError):
            status.phase = EnginePhase.FAILED


class TestTrayStatusLabel:
    """The label used to be built by taking the engine's sentence apart.
    It is now a pure function of the status, testable without GTK."""

    def test_download_shows_the_percentage(self):
        label = status_label(EngineStatus(EnginePhase.DOWNLOADING, percent=42),
                             enabled=True, mode="hold", key="F12")
        assert label == "Downloading speech model… 42% (one time)"

    def test_download_at_zero_still_reads_sensibly(self):
        """The old code printed '0%' via a fallback for an empty string;
        with a real integer there is no empty case to fall back from."""
        label = status_label(EngineStatus(EnginePhase.DOWNLOADING, percent=0),
                             enabled=True, mode="hold", key="F12")
        assert "0%" in label

    @pytest.mark.parametrize("phase", [EnginePhase.LOADING, EnginePhase.NOT_LOADED])
    def test_preparing(self, phase):
        assert status_label(EngineStatus(phase), enabled=True, mode="hold",
                            key="F12") == "Preparing speech model…"

    def test_failure_points_at_the_status_command(self):
        label = status_label(EngineStatus(EnginePhase.FAILED, error="boom"),
                             enabled=True, mode="hold", key="F12")
        assert "failed" in label

    def test_ready_reflects_mode_and_key(self):
        ready = EngineStatus(EnginePhase.READY)
        assert status_label(ready, enabled=True, mode="hold", key="F12") == \
            "Ready — hold F12 to dictate"
        assert status_label(ready, enabled=True, mode="toggle", key="PAUSE") == \
            "Ready — press PAUSE to start/stop"

    def test_disabled_beats_ready_but_not_the_engine_states(self):
        """Being disabled is worth showing, but not instead of telling
        the user the model is still downloading."""
        assert status_label(EngineStatus(EnginePhase.READY), enabled=False,
                            mode="hold", key="F12") == "Disabled"
        assert "Downloading" in status_label(
            EngineStatus(EnginePhase.DOWNLOADING, percent=5),
            enabled=False, mode="hold", key="F12")


class LoadingEngine:
    """A fake that can actually imitate the load path.

    The point of the typed status: the previous fakes implemented the
    three members the protocol declared, while the daemon used six, so
    start_engine() raised AttributeError and this path had no tests.
    """

    def __init__(self, cached=True, fails=False):
        self._cached = cached
        self._fails = fails
        self.status = EngineStatus(EnginePhase.NOT_LOADED)
        self.downloaded = False
        self.load_finished = False

    def is_cached(self):
        return self._cached

    def load(self):
        self.downloaded = not self._cached
        self.status = (EngineStatus(EnginePhase.FAILED, error="no disk space")
                       if self._fails else EngineStatus(EnginePhase.READY))
        self.load_finished = True

    def warm_up(self):
        pass

    def transcribe(self, samples, sample_rate):
        return ""


def make_daemon(engine):
    daemon = Daemon(make_settings(), engine=engine, desktop=_FakeDesktop())
    daemon.desktop.notifications = []
    daemon.desktop.notify = lambda summary, body="": \
        daemon.desktop.notifications.append((summary, body))
    return daemon


class TestLoadPath:
    def test_cached_model_loads_without_notifications(self):
        daemon = make_daemon(LoadingEngine(cached=True))
        daemon._load_engine()
        assert daemon.desktop.notifications == []
        assert daemon.engine.status.phase is EnginePhase.READY

    def test_first_run_announces_the_download_and_then_readiness(self):
        daemon = make_daemon(LoadingEngine(cached=False))
        daemon._load_engine()
        summaries = [s for s, _ in daemon.desktop.notifications]
        assert summaries == ["Downloading the speech model", "AgentWhisper is ready"]

    def test_failure_is_reported_with_the_reason(self):
        daemon = make_daemon(LoadingEngine(cached=True, fails=True))
        daemon._load_engine()
        summary, body = daemon.desktop.notifications[-1]
        assert summary == "Speech model failed to load"
        assert body == "error: no disk space"

    def test_status_command_renders_the_engine_for_humans(self):
        daemon = make_daemon(LoadingEngine(cached=True))
        daemon.engine.status = EngineStatus(EnginePhase.DOWNLOADING, percent=7)
        assert daemon.handle_request({"cmd": "status"})["engine"] == "downloading 7%"
