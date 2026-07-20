"""PyAV must stay out of the process.

faster-whisper pulls in av (with a bundled FFmpeg) purely for
decode_audio(), which AgentWhisper never calls. This is worth a test
rather than a comment: a dependency bump that starts touching av at
import time would silently put 16MB back, and nothing else would fail.
"""

import subprocess
import sys
import textwrap

import pytest

from agentwhisper.engines.whisper_local import _skip_pyav_import


def run_in_fresh_interpreter(source: str) -> str:
    """faster_whisper can only be imported once per process, so these
    checks need their own interpreter to mean anything."""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestPyAVIsNotLoaded:
    def test_placeholder_satisfies_the_import(self):
        _skip_pyav_import()
        assert "av" in sys.modules
        assert sys.modules["av"].__name__ == "av"

    def test_placeholder_is_not_installed_twice(self):
        _skip_pyav_import()
        first = sys.modules["av"]
        _skip_pyav_import()
        assert sys.modules["av"] is first

    @pytest.mark.slow
    def test_importing_the_engine_does_not_load_pyav(self):
        """The real guarantee: loading faster-whisper the way the engine
        does must leave the actual av package unimported."""
        out = run_in_fresh_interpreter("""
            import sys
            from agentwhisper.engines.whisper_local import _skip_pyav_import
            _skip_pyav_import()
            from faster_whisper import WhisperModel  # noqa: F401
            # __dict__, not getattr: a placeholder answering __file__
            # through __getattr__ would make this check meaningless.
            av = sys.modules["av"]
            print("real" if av.__dict__.get("__file__") else "placeholder")
        """)
        assert out == "placeholder"

    @pytest.mark.slow
    def test_transcription_works_without_pyav(self):
        """A placeholder that broke transcription would be worse than the
        16MB. Runs a real model, so it is marked slow."""
        out = run_in_fresh_interpreter("""
            import numpy as np
            from agentwhisper.engines.whisper_local import WhisperLocalEngine

            engine = WhisperLocalEngine("tiny")
            engine.load()
            assert engine.status == "ready", engine.status
            engine.transcribe(np.zeros(16_000, dtype=np.int16), 16_000)
            print("ok")
        """)
        assert out == "ok"
