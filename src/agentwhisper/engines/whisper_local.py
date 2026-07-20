"""Local speech-to-text via faster-whisper. Private, offline, free.

The first load downloads the model from Hugging Face
(~40MB tiny … ~3GB large-v3) into ~/.cache/huggingface; after
that everything is offline.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import sys
import threading
import time
import types
from pathlib import Path

import numpy as np

from agentwhisper.engines.base import EngineError, EnginePhase, EngineStatus

log = logging.getLogger("agentwhisper.engine")

# How long transcribe() waits for the model to finish loading before
# giving up (first-ever run may be downloading on slow connections).
LOAD_WAIT_SECONDS = 600


def _return_freed_memory_to_the_os() -> None:
    """Ask glibc to give back the arenas freed by unloading the weights.

    Dropping the model frees the memory inside the process, but glibc
    keeps the arenas for reuse, so RSS barely moves — measured on the
    'small' model: 687 MB before, 420 MB after free(), 173 MB after this
    call. Without it the unload is worth about a third of what it looks
    like. Absent on non-glibc systems, where it is simply skipped.
    """
    with contextlib.suppress(OSError, AttributeError):
        ctypes.CDLL("libc.so.6").malloc_trim(0)


def _skip_pyav_import() -> None:
    """Keep PyAV (and its bundled FFmpeg) out of the process.

    faster-whisper's package __init__ imports decode_audio, which imports
    av at module level — 16 MB of resident memory and ~100 MB on disk for
    a decoder this engine never reaches: transcribe() is handed a numpy
    array from the recorder, so no file is ever decoded.

    Registering a placeholder under the name satisfies the import without
    loading the library. Every av.* call in faster-whisper sits inside a
    function body, none at module level, so nothing touches the
    placeholder unless decode_audio() is called — and if some future
    version does call it, it raises with an explanation instead of
    failing obscurely.

    Must run before ANY faster_whisper import, including the
    faster_whisper.utils ones, because those execute the package
    __init__ too.
    """
    if "av" in sys.modules:
        return
    placeholder = types.ModuleType("av")
    placeholder.__doc__ = (
        "Placeholder installed by AgentWhisper: PyAV is deliberately not "
        "installed, because faster-whisper only needs it to decode audio "
        "files and AgentWhisper transcribes in-memory samples."
    )

    def _unavailable(*_args, **_kwargs):
        raise EngineError(
            "this build of AgentWhisper cannot decode audio files "
            "(PyAV is not installed)")

    def _attribute(name: str):
        # Dunders must fail the ordinary way: answering __file__ or
        # __version__ with a callable would make the placeholder lie to
        # anything that inspects it, including tests asserting it is one.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _unavailable

    placeholder.__getattr__ = _attribute
    sys.modules["av"] = placeholder


class WhisperLocalEngine:
    def __init__(self, model: str, device: str = "cpu", compute_type: str = "int8",
                 unload_after_seconds: int = 0):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.unload_after_seconds = unload_after_seconds
        self._model = None
        self._phase = EnginePhase.NOT_LOADED
        self._error = ""
        self._loaded = threading.Event()
        self.downloaded = False  # True if load() had to download the model
        self._expected_bytes = 0  # remote size of the model being downloaded
        # Held across every use of the weights, so the idle timer can
        # never unload them out from under a transcription in flight.
        self._residency = threading.RLock()
        self._unload_timer: threading.Timer | None = None

    @property
    def status(self) -> EngineStatus:
        if self._phase is EnginePhase.DOWNLOADING:
            return EngineStatus(EnginePhase.DOWNLOADING, percent=self.progress)
        return EngineStatus(self._phase, error=self._error)

    @property
    def load_finished(self) -> bool:
        """True once load() has ended, in success or failure."""
        return self._loaded.is_set()

    def is_cached(self) -> bool:
        """True only if the model is COMPLETELY downloaded.

        A directory-exists check is not enough: an interrupted download
        leaves a partial cache directory behind, and the app would then
        claim "loading" while it is actually resuming a download.
        faster-whisper's own download helper with local_files_only=True
        succeeds only when every required file is present.
        """
        try:
            _skip_pyav_import()
            from faster_whisper.utils import download_model

            download_model(self.model_name, local_files_only=True)
            return True
        except Exception:
            return False

    def _repo_id(self) -> str:
        _skip_pyav_import()
        from faster_whisper.utils import _MODELS

        return _MODELS.get(self.model_name, self.model_name)

    def _blobs_dir(self) -> Path:
        hf_home = Path(os.environ.get("HF_HOME",
                                      Path.home() / ".cache" / "huggingface"))
        return hf_home / "hub" / ("models--" + self._repo_id().replace("/", "--")) / "blobs"

    def _fetch_expected_bytes(self) -> int:
        """Total size of the files faster-whisper will download, from the
        Hugging Face API. 0 if it can't be determined (progress then
        just isn't shown)."""
        import fnmatch

        from huggingface_hub import HfApi

        patterns = ["config.json", "preprocessor_config.json",
                    "model.bin", "tokenizer.json", "vocabulary.*"]
        try:
            info = HfApi().model_info(self._repo_id(), files_metadata=True)
            return sum(
                s.size or 0 for s in info.siblings
                if any(fnmatch.fnmatch(s.rfilename, p) for p in patterns)
            )
        except Exception as e:
            log.warning("could not determine model download size: %s", e)
            return 0

    @property
    def progress(self) -> int:
        """Download progress 0-99, measured from bytes on disk — robust
        regardless of how the downloader reports (and it counts resumed
        partial files for free)."""
        if not self._expected_bytes:
            return 0
        try:
            done = sum(f.stat().st_size for f in self._blobs_dir().glob("*")
                       if f.is_file())
        except OSError:
            return 0
        return min(99, int(100 * done / self._expected_bytes))

    def load(self) -> None:
        _skip_pyav_import()
        from faster_whisper import WhisperModel

        cached = self.is_cached()
        self.downloaded = not cached
        self._phase = EnginePhase.LOADING if cached else EnginePhase.DOWNLOADING
        log.info("%s whisper model %r",
                 "loading" if cached else "downloading (first run)", self.model_name)
        started = time.time()
        try:
            if not cached:
                self._expected_bytes = self._fetch_expected_bytes()
            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type
            )
        except Exception as e:
            self._phase = EnginePhase.FAILED
            self._error = str(e)
            log.error("model load failed: %s", e)
        else:
            self._phase = EnginePhase.READY
            log.info("model %r ready in %.1fs", self.model_name, time.time() - started)
            self._schedule_unload()
        finally:
            self._loaded.set()

    # -- weight residency ------------------------------------------------
    #
    # The model is a few hundred megabytes and dictation is a few seconds
    # a day, so the weights are dropped again after an idle period and
    # brought back when they are next needed. This is entirely internal:
    # `status` still says "ready" while unloaded, because from the outside
    # nothing has changed — transcribe() always works.

    @property
    def resident(self) -> bool:
        """True if the weights are currently in memory."""
        return self._model is not None and self._model.model.model_is_loaded

    def warm_up(self) -> None:
        """Bring the weights back if they were dropped. Safe to call from
        anywhere, any number of times; blocks until they are resident.

        The daemon calls this the moment recording starts, so the reload
        (0.3s for 'base', ~1.0s for 'small') runs while the user is still
        speaking and never shows up as a delay.
        """
        if not self._loaded.is_set() or self._model is None:
            return  # the initial load owns the weights until it is done
        with self._residency:
            self._ensure_resident()
            self._schedule_unload()

    def _ensure_resident(self) -> None:
        """Caller must hold self._residency."""
        if self._model is None or self._model.model.model_is_loaded:
            return
        started = time.time()
        self._model.model.load_model()
        log.info("model %r reloaded in %.2fs", self.model_name, time.time() - started)

    def _schedule_unload(self) -> None:
        if not self.unload_after_seconds:
            return
        if self._unload_timer is not None:
            self._unload_timer.cancel()
        self._unload_timer = threading.Timer(self.unload_after_seconds, self._unload)
        self._unload_timer.daemon = True
        self._unload_timer.start()

    def _unload(self) -> None:
        with self._residency:
            if self._model is None or not self._model.model.model_is_loaded:
                return
            self._model.model.unload_model(to_cpu=False)
            _return_freed_memory_to_the_os()
            log.info("model %r unloaded after %ds idle", self.model_name,
                     self.unload_after_seconds)

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        if not self._loaded.wait(timeout=LOAD_WAIT_SECONDS):
            raise EngineError("the model is still loading — try again shortly")
        if self._model is None:
            raise EngineError(f"the model failed to load ({self.status.describe()})")
        if sample_rate != 16_000:
            raise EngineError(f"expected 16kHz audio, got {sample_rate}Hz")

        audio = samples.astype(np.float32) / 32768.0
        # language is deliberately not passed: the general models figure
        # out the spoken language themselves, whatever it is.
        with self._residency:
            self._ensure_resident()
            try:
                segments, _info = self._model.transcribe(
                    audio, beam_size=5, vad_filter=True
                )
                return " ".join(s.text.strip() for s in segments).strip()
            finally:
                self._schedule_unload()
