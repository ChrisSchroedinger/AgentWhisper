"""Which panel icon is shown, and whether it exists.

Constructing a Tray needs GTK, so the choice is a pure function and the
files are checked directly: a name with no matching .svg leaves an empty
space in the panel, and nothing else would catch that.
"""

from pathlib import Path

import pytest
from tests.helpers import make_settings
from tests.test_daemon import _FakeDesktop, _FakeEngine

from agentwhisper.daemon import Daemon
from agentwhisper.tray import (
    ICON_DISABLED,
    ICON_IDLE,
    ICON_RECORDING,
    _icon_dir,
    idle_icon,
)


def test_disabled_gets_its_own_icon():
    assert idle_icon(enabled=True) == ICON_IDLE
    assert idle_icon(enabled=False) == ICON_DISABLED


@pytest.mark.parametrize("name", [ICON_IDLE, ICON_RECORDING, ICON_DISABLED])
def test_every_icon_the_panel_asks_for_is_shipped(name):
    assert (Path(_icon_dir()) / f"{name}.svg").is_file()


class _FakeTray:
    def __init__(self):
        self.states = []

    def set_state(self, state):
        self.states.append(state)


class TestTrayFollowsTheToggle:
    """The icon has to change on `agentwhisper toggle` too, not only on
    a click in the menu — the daemon is what both go through."""

    @pytest.fixture
    def daemon(self):
        daemon = Daemon(make_settings(), engine=_FakeEngine(),
                        desktop=_FakeDesktop())
        daemon._tray = _FakeTray()
        return daemon

    def test_toggling_refreshes_the_panel(self, daemon):
        daemon.handle_request({"cmd": "toggle-enabled"})
        assert daemon._tray.states == ["idle"]
        assert idle_icon(daemon.is_enabled()) == ICON_DISABLED

    def test_and_again_on_the_way_back(self, daemon):
        daemon.set_enabled(False)
        daemon.set_enabled(True)
        assert daemon._tray.states == ["idle", "idle"]
        assert idle_icon(daemon.is_enabled()) == ICON_IDLE
