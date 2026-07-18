"""Local speech-to-text via faster-whisper. Private, offline, free.

The first load downloads the model from Hugging Face
(~40MB tiny … ~3GB large-v3) into ~/.cache/huggingface; after
that everything is offline.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import numpy as np

from agentwhisper.engines.base import EngineError

log = logging.getLogger("agentwhisper.engine")

# How long transcribe() waits for the model to finish loading before
# giving up (first-ever run may be downloading on slow connections).
LOAD_WAIT_SECONDS = 600


class WhisperLocalEngine:
    def __init__(self, model: str, device: str = "cpu", compute_type: str = "int8"):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._status = "not loaded"
        self._loaded = threading.Event()
        self.downloaded = False  # True if load() had to download the model
        self._expected_bytes = 0  # remote size of the model being downloaded

    @property
    def status(self) -> str:
        if self._status == "downloading":
            return f"downloading {self.progress}%"
        return self._status

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
            from faster_whisper.utils import download_model

            download_model(self.model_name, local_files_only=True)
            return True
        except Exception:
            return False

    def _repo_id(self) -> str:
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
        from faster_whisper import WhisperModel

        cached = self.is_cached()
        self.downloaded = not cached
        self._status = "loading" if cached else "downloading"
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
            self._status = f"error: {e}"
            log.error("model load failed: %s", e)
        else:
            self._status = "ready"
            log.info("model %r ready in %.1fs", self.model_name, time.time() - started)
        finally:
            self._loaded.set()

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> str:
        if not self._loaded.wait(timeout=LOAD_WAIT_SECONDS):
            raise EngineError("the model is still loading — try again shortly")
        if self._model is None:
            raise EngineError(f"the model failed to load ({self._status})")
        if sample_rate != 16_000:
            raise EngineError(f"expected 16kHz audio, got {sample_rate}Hz")

        audio = samples.astype(np.float32) / 32768.0
        # language is deliberately not passed: the general models figure
        # out the spoken language themselves, whatever it is.
        segments, _info = self._model.transcribe(
            audio, beam_size=5, vad_filter=True
        )
        return " ".join(s.text.strip() for s in segments).strip()
