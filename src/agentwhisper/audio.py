"""Microphone capture via sounddevice (PortAudio), in-process.

No arecord shell-out: we get device errors as exceptions at start(),
and a live RMS level for the recording visualizer for free.
"""

from __future__ import annotations

import threading

import numpy as np

SAMPLE_RATE = 16_000  # what whisper expects
CHANNELS = 1
DTYPE = "int16"


class AudioError(Exception):
    """Recording cannot work; the message says why and what to do."""


class Recorder:
    """One recording at a time; start() → speak → stop() → samples."""

    def __init__(self):
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._level = 0.0

    @property
    def level(self) -> float:
        """Latest RMS level, 0.0–1.0; safe to read from any thread."""
        return self._level

    @property
    def active(self) -> bool:
        return self._stream is not None

    def _callback(self, indata, frames, time_info, status):
        with self._lock:
            self._chunks.append(indata.copy())
        samples = indata.astype(np.float32) / 32768.0
        self._level = float(np.sqrt(np.mean(samples**2)))

    def start(self) -> None:
        import sounddevice as sd

        if self._stream is not None:
            return
        self._chunks = []
        self._level = 0.0
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                callback=self._callback,
            )
            self._stream.start()
        except sd.PortAudioError as e:
            self._stream = None
            raise AudioError(
                f"cannot open the microphone: {e}. Check that an input device "
                f"exists (arecord -l) and is not exclusively used by another app."
            ) from e

    def stop(self) -> tuple[np.ndarray, float]:
        """Stop capturing; return (mono int16 samples, duration in seconds)."""
        if self._stream is None:
            return np.zeros(0, dtype=np.int16), 0.0
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self._level = 0.0
        with self._lock:
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.int16), 0.0
        samples = np.concatenate(chunks).reshape(-1)
        return samples, len(samples) / SAMPLE_RATE
