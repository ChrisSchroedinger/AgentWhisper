"""The engine drops the model's weights while idle and brings them back.

Driven against a stand-in for faster-whisper's model handle so the tests
run in a second without downloading a real model.
"""

import threading

import numpy as np
import pytest

from agentwhisper.engines.base import EngineError
from agentwhisper.engines.whisper_local import WhisperLocalEngine

SAMPLES = np.zeros(1600, dtype=np.int16)


class FakeCT2Model:
    """Stands in for ctranslate2.models.Whisper."""

    def __init__(self):
        self.model_is_loaded = True
        self.loads = 0
        self.unloads = 0

    def load_model(self):
        self.model_is_loaded = True
        self.loads += 1

    def unload_model(self, to_cpu=False):
        self.model_is_loaded = False
        self.unloads += 1


class FakeWhisperModel:
    """Stands in for faster_whisper.WhisperModel."""

    def __init__(self):
        self.model = FakeCT2Model()
        self.transcriptions = 0

    def transcribe(self, audio, **kwargs):
        assert self.model.model_is_loaded, "transcribed while the weights were unloaded"
        self.transcriptions += 1
        return [type("Seg", (), {"text": " hi "})()], None


def make_engine(unload_after_seconds=300):
    """An engine in the state load() leaves it in, without the download."""
    engine = WhisperLocalEngine("base", unload_after_seconds=unload_after_seconds)
    engine._model = FakeWhisperModel()
    engine._status = "ready"
    engine._loaded.set()
    return engine


class TestResidency:
    def test_unloading_frees_the_weights(self):
        engine = make_engine()
        assert engine.resident
        engine._unload()
        assert not engine.resident
        assert engine._model.model.unloads == 1

    def test_transcribe_reloads_transparently(self):
        engine = make_engine()
        engine._unload()
        assert engine.transcribe(SAMPLES, 16_000) == "hi"
        assert engine.resident
        assert engine._model.model.loads == 1

    def test_warm_up_reloads_before_transcription(self):
        engine = make_engine()
        engine._unload()
        engine.warm_up()
        assert engine.resident
        # Already warm: warming again must not reload a second time.
        engine.warm_up()
        assert engine._model.model.loads == 1

    def test_status_stays_ready_while_unloaded(self):
        """Residency is internal — nothing outside the engine should be
        able to tell, or the tray would report a state the user cannot act on."""
        engine = make_engine()
        engine._unload()
        assert engine.status == "ready"

    def test_unload_is_scheduled_after_transcribing(self):
        engine = make_engine(unload_after_seconds=30)
        engine.transcribe(SAMPLES, 16_000)
        assert engine._unload_timer is not None
        assert engine._unload_timer.interval == 30
        engine._unload_timer.cancel()

    def test_zero_disables_unloading(self):
        engine = make_engine(unload_after_seconds=0)
        engine.transcribe(SAMPLES, 16_000)
        assert engine._unload_timer is None
        assert engine.resident

    def test_idle_timer_cannot_unload_mid_transcription(self):
        """The residency lock is the whole safety story: ctranslate2 raises
        'No model replica is available' if the weights vanish under a
        transcription, and that would surface as a failed dictation."""
        engine = make_engine()
        started = threading.Event()
        release = threading.Event()

        real_transcribe = engine._model.transcribe

        def slow_transcribe(audio, **kwargs):
            started.set()
            release.wait(timeout=5)
            return real_transcribe(audio, **kwargs)

        engine._model.transcribe = slow_transcribe
        result = {}
        worker = threading.Thread(
            target=lambda: result.update(text=engine.transcribe(SAMPLES, 16_000)))
        worker.start()
        assert started.wait(timeout=5)

        unloader = threading.Thread(target=engine._unload)
        unloader.start()
        unloader.join(timeout=0.5)
        assert unloader.is_alive(), "the unload should be blocked by the transcription"

        release.set()
        worker.join(timeout=5)
        unloader.join(timeout=5)
        assert result["text"] == "hi"
        assert engine._model.transcriptions == 1

    def test_warm_up_before_the_first_load_is_a_no_op(self):
        """Pressing the hotkey while the model is still downloading must
        not touch the weights the initial load is still building."""
        engine = WhisperLocalEngine("base", unload_after_seconds=300)
        engine.warm_up()  # no _model yet, _loaded not set
        assert engine._model is None
        assert engine._unload_timer is None

    def test_a_failed_load_still_reports_the_error(self):
        engine = WhisperLocalEngine("base", unload_after_seconds=300)
        engine._status = "error: no disk space"
        engine._loaded.set()
        with pytest.raises(EngineError, match="failed to load"):
            engine.transcribe(SAMPLES, 16_000)


class TestWarmUpOnRecording:
    def test_recording_warms_the_engine_up(self):
        """The reload has to start with the recording, not with the
        transcription — that is what keeps it invisible to the user."""
        from test_pipeline import make_daemon

        daemon = make_daemon()
        daemon.on_hotkey_press()
        for _ in range(50):
            if daemon.engine.warm_ups:
                break
            threading.Event().wait(0.01)
        assert daemon.engine.warm_ups == 1
        daemon._stop_recording(discard=True)
