"""X11 desktop backend: background typing (focus without raise) and
window-list parsing helpers."""

from __future__ import annotations

import subprocess

import pytest

from agentwhisper.desktop.base import DesktopError
from agentwhisper.desktop.x11 import X11Desktop, _best_icon
from agentwhisper.tray import _argb_to_rgba


class RunRecorder:
    """Stands in for subprocess.run; records each xdotool call and
    scripts the replies."""

    def __init__(self, active_window=b"999", fail_on=None):
        self.calls: list[list[str]] = []
        self.active_window = active_window
        self.fail_on = fail_on  # xdotool subcommand that raises

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        subcommand = argv[1]
        if subcommand == self.fail_on:
            raise subprocess.CalledProcessError(1, argv, stderr=b"boom")

        class Result:
            stdout = self.active_window if subcommand == "getactivewindow" else b""

        return Result()

    def subcommands(self):
        return [argv[1] for argv in self.calls]


class TestTypeIntoWindow:
    def test_focuses_types_and_restores_without_raising(self, monkeypatch):
        run = RunRecorder(active_window=b"999")
        monkeypatch.setattr(subprocess, "run", run)
        X11Desktop().type_into_window("123", "hello")
        assert run.subcommands() == [
            "getactivewindow", "windowfocus", "type", "key", "windowfocus"]
        assert run.calls[1] == ["xdotool", "windowfocus", "--sync", "123"]
        assert run.calls[4] == ["xdotool", "windowfocus", "999"]
        assert "windowactivate" not in run.subcommands()  # never raised/front

    def test_no_restore_when_target_already_focused(self, monkeypatch):
        run = RunRecorder(active_window=b"123")
        monkeypatch.setattr(subprocess, "run", run)
        X11Desktop().type_into_window("123", "hello")
        assert run.subcommands() == ["getactivewindow", "windowfocus", "type", "key"]

    def test_focus_restored_even_when_typing_fails(self, monkeypatch):
        run = RunRecorder(active_window=b"999", fail_on="type")
        monkeypatch.setattr(subprocess, "run", run)
        with pytest.raises(DesktopError):
            X11Desktop().type_into_window("123", "hello")
        assert run.calls[-1] == ["xdotool", "windowfocus", "999"]

    def test_typing_proceeds_when_active_window_unknown(self, monkeypatch):
        run = RunRecorder(fail_on="getactivewindow")
        monkeypatch.setattr(subprocess, "run", run)
        X11Desktop().type_into_window("123", "hello")
        assert run.subcommands() == ["getactivewindow", "windowfocus", "type", "key"]


class TestBestIcon:
    def test_picks_size_closest_to_48(self):
        data = ([2, 2] + [0] * 4) + ([48, 48] + [0] * 48 * 48) + ([128, 128] + [0] * 128 * 128)
        width, height, pixels = _best_icon(data)
        assert (width, height) == (48, 48)
        assert len(pixels) == 48 * 48

    def test_single_icon(self):
        assert _best_icon([1, 1, 42]) == (1, 1, [42])

    def test_truncated_data_is_rejected(self):
        assert _best_icon([64, 64, 1, 2, 3]) is None

    def test_empty_and_garbage(self):
        assert _best_icon([]) is None
        assert _best_icon([0, 0]) is None

    def test_reads_the_x_property_in_place(self):
        """python-xlib hands the property over as an array of 32-bit
        ints. Converting the whole thing to Python ints to find one icon
        costs about ten times the array itself, so only the chosen block
        is converted — the result must be identical either way."""
        import array

        blocks = ([16, 16] + [0x11223344] * 256
                  + [48, 48] + [0xAABBCCDD] * 2304
                  + [256, 256] + [0x99887766] * 65536)
        packed = array.array("I", blocks)
        assert _best_icon(packed) == _best_icon(blocks)
        width, height, pixels = _best_icon(packed)
        assert (width, height) == (48, 48)
        assert set(pixels) == {0xAABBCCDD}


class TestArgbToRgba:
    def test_reorders_channels(self):
        # ARGB 0xAA112233 → RGBA (0x11, 0x22, 0x33, 0xAA)
        assert _argb_to_rgba([0xAA112233], 1, 1) == bytes([0x11, 0x22, 0x33, 0xAA])

    def test_masks_oversized_values(self):
        # X servers on 64-bit may hand back longs with junk upper bits.
        assert _argb_to_rgba([0xFF00AA112233], 1, 1) == bytes([0x11, 0x22, 0x33, 0xAA])
