"""State machine tests, including the X11 auto-repeat scenarios that
motivated the rewrite."""

from agentwhisper.state import Action, DictationStateMachine, Phase


def drain_autorepeat(sm, cycles):
    """Simulate X11 auto-repeat: synthetic release+press pairs while held."""
    actions = []
    for _ in range(cycles):
        actions += sm.key_released()   # synthetic release
        actions += sm.key_pressed()    # synthetic press ~30ms later
    return actions


class TestHoldMode:
    def test_press_starts_release_stops(self):
        sm = DictationStateMachine(mode="hold")
        assert sm.key_pressed() == [Action.START_RECORDING]
        assert sm.phase is Phase.RECORDING
        assert sm.key_released() == [Action.SCHEDULE_SETTLE]
        assert sm.release_settled() == [Action.STOP_RECORDING]
        assert sm.phase is Phase.TRANSCRIBING
        sm.transcription_finished()
        assert sm.phase is Phase.IDLE

    def test_autorepeat_does_not_stop_recording(self):
        """The soupawhisper bug: holding the key must be ONE recording."""
        sm = DictationStateMachine(mode="hold")
        sm.key_pressed()
        actions = drain_autorepeat(sm, cycles=50)
        # Every synthetic release schedules a settle; every synthetic
        # press cancels it. Recording never stops in between.
        assert Action.STOP_RECORDING not in actions
        assert sm.phase is Phase.RECORDING
        assert actions.count(Action.SCHEDULE_SETTLE) == 50
        assert actions.count(Action.CANCEL_SETTLE) == 50
        # Real release finally stops it.
        sm.key_released()
        assert sm.release_settled() == [Action.STOP_RECORDING]

    def test_settle_after_cancel_is_noop(self):
        """Timer callback racing a cancel must not stop recording."""
        sm = DictationStateMachine(mode="hold")
        sm.key_pressed()
        sm.key_released()
        sm.key_pressed()  # auto-repeat: cancels the settle
        assert sm.release_settled() == []  # stale timer fires anyway
        assert sm.phase is Phase.RECORDING

    def test_press_while_transcribing_starts_nothing(self):
        sm = DictationStateMachine(mode="hold")
        sm.key_pressed()
        sm.key_released()
        sm.release_settled()
        assert sm.phase is Phase.TRANSCRIBING
        assert sm.key_pressed() == []
        assert sm.phase is Phase.TRANSCRIBING


class TestToggleMode:
    def test_tap_starts_tap_stops(self):
        sm = DictationStateMachine(mode="toggle")
        assert sm.key_pressed() == [Action.START_RECORDING]
        sm.key_released()
        sm.release_settled()
        assert sm.phase is Phase.RECORDING  # release does not stop toggle mode
        assert sm.key_pressed() == [Action.STOP_RECORDING]
        assert sm.phase is Phase.TRANSCRIBING

    def test_holding_key_toggles_once_despite_autorepeat(self):
        sm = DictationStateMachine(mode="toggle")
        assert sm.key_pressed() == [Action.START_RECORDING]
        actions = drain_autorepeat(sm, cycles=50)
        assert Action.STOP_RECORDING not in actions
        assert Action.START_RECORDING not in actions
        assert sm.phase is Phase.RECORDING


class TestLifecycle:
    def test_max_duration_stops_recording(self):
        sm = DictationStateMachine(mode="hold")
        sm.key_pressed()
        assert sm.max_duration_reached() == [Action.STOP_RECORDING]
        assert sm.phase is Phase.TRANSCRIBING

    def test_disable_aborts_active_recording(self):
        sm = DictationStateMachine(mode="hold")
        sm.key_pressed()
        assert sm.set_enabled(False) == [Action.ABORT_RECORDING]
        assert sm.phase is Phase.IDLE
        # While disabled, presses do nothing.
        sm.key_released()
        sm.release_settled()
        assert sm.key_pressed() == []

    def test_reenable_allows_recording_again(self):
        sm = DictationStateMachine(mode="hold")
        sm.set_enabled(False)
        sm.key_pressed()
        sm.key_released()
        sm.release_settled()
        sm.set_enabled(True)
        assert sm.key_pressed() == [Action.START_RECORDING]

    def test_shutdown_mid_recording_aborts(self):
        sm = DictationStateMachine(mode="hold")
        sm.key_pressed()
        assert sm.shutdown() == [Action.ABORT_RECORDING]

    def test_shutdown_idle_is_clean(self):
        sm = DictationStateMachine(mode="hold")
        assert sm.shutdown() == []


class TestCancel:
    def test_cancel_mid_recording_aborts(self):
        sm = DictationStateMachine(mode="hold")
        sm.key_pressed()
        assert sm.cancel_requested() == [Action.ABORT_RECORDING]
        assert sm.phase is Phase.IDLE

    def test_hotkey_release_after_cancel_does_nothing(self):
        """Hold mode: Esc fires while the hotkey is still held; the
        release that follows must not start a transcription."""
        sm = DictationStateMachine(mode="hold")
        sm.key_pressed()
        sm.cancel_requested()
        assert sm.key_released() == [Action.SCHEDULE_SETTLE]
        assert sm.release_settled() == []
        assert sm.phase is Phase.IDLE
        # And the next press records again.
        assert sm.key_pressed() == [Action.START_RECORDING]

    def test_cancel_in_toggle_mode_then_restart(self):
        sm = DictationStateMachine(mode="toggle")
        sm.key_pressed()
        sm.key_released()
        sm.release_settled()
        assert sm.cancel_requested() == [Action.ABORT_RECORDING]
        assert sm.key_pressed() == [Action.START_RECORDING]

    def test_cancel_when_idle_or_transcribing_is_a_noop(self):
        sm = DictationStateMachine(mode="hold")
        assert sm.cancel_requested() == []
        sm.key_pressed()
        sm.max_duration_reached()  # now TRANSCRIBING
        assert sm.cancel_requested() == []
        assert sm.phase is Phase.TRANSCRIBING


class TestModeSwitching:
    def test_switch_while_idle_is_silent(self):
        sm = DictationStateMachine(mode="hold")
        assert sm.set_mode("toggle") == []
        assert sm.mode == "toggle"

    def test_switch_mid_recording_aborts(self):
        sm = DictationStateMachine(mode="hold")
        sm.key_pressed()
        assert sm.set_mode("toggle") == [Action.ABORT_RECORDING]
        assert sm.phase is Phase.IDLE
        assert sm.mode == "toggle"

    def test_same_mode_mid_recording_keeps_recording(self):
        sm = DictationStateMachine(mode="hold")
        sm.key_pressed()
        assert sm.set_mode("hold") == []
        assert sm.phase is Phase.RECORDING

    def test_new_mode_takes_effect(self):
        sm = DictationStateMachine(mode="hold")
        sm.set_mode("toggle")
        sm.key_pressed()          # starts
        sm.key_released()
        sm.release_settled()      # release must NOT stop in toggle mode
        assert sm.phase is Phase.RECORDING

    def test_invalid_mode_raises(self):
        sm = DictationStateMachine(mode="hold")
        import pytest
        with pytest.raises(ValueError):
            sm.set_mode("press")
