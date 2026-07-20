"""Settings — the one owner of every value that persists.

Before this module the daemon changed a field, called `config.save()`
and hoped: the range checks lived in two places, the write was a plain
`write_text` (a full disk left a truncated file), a failure raised into
a GTK callback where nobody saw it, and `mode` existed twice — once in
the config and once in the state machine — so every caller had to
remember to set both.

`change()` replaces all of that with one path:

1. validate the whole config *with the change applied*, so a value is
   judged in context and by the same rules the file is judged by;
2. write the file atomically, so a crash or a full disk leaves the
   previous file intact;
3. only then swap the values in and tell the subscribers.

Every step can refuse, and refusing changes nothing. So a caller that
gets no exception knows the setting is really stored, and a caller that
gets one knows nothing moved — which is what makes it safe to put the
tray checkbox back where it was.
"""

from __future__ import annotations

import dataclasses
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from agentwhisper import config as config_mod
from agentwhisper.config import CONFIG_PATH, Config, ConfigError


class Settings:
    """The current settings and the file behind them."""

    def __init__(self, values: Config, path: Path = CONFIG_PATH) -> None:
        self._values = values
        self._path = path
        self._lock = threading.RLock()
        self._subscribers: list[Callable[[Config], None]] = []

    @property
    def values(self) -> Config:
        """The settings as they are right now.

        Read freely; write through `change()`. A field assigned here
        would skip validation and never reach the file.
        """
        return self._values

    def subscribe(self, callback: Callable[[Config], None]) -> None:
        """Register a callback to run after each successful change.

        This is how state that mirrors a setting stays honest: the
        state machine's `mode` is refreshed from here, so it cannot
        drift no matter who changed the setting or how.
        """
        self._subscribers.append(callback)

    def change(self, **updates: object) -> None:
        """Apply, persist and announce a change. Raise, and change nothing.

        Raises ConfigError naming an unknown setting, listing every
        invalid value, or explaining why the file could not be written.
        """
        with self._lock:
            try:
                candidate = dataclasses.replace(self._values, **updates)  # type: ignore[arg-type]
            except TypeError as e:
                raise ConfigError(f"unknown setting: {e}") from e
            problems = candidate.validate()
            if problems:
                raise ConfigError("; ".join(problems))
            self._write(candidate)
            self._values = candidate
        # Outside the lock: a subscriber takes locks of its own, and
        # holding this one across a callback invites the classic
        # two-lock deadlock.
        for callback in self._subscribers:
            callback(candidate)

    def _write(self, values: Config) -> None:
        """Replace the file in a single step.

        A temporary file in the same directory plus os.replace: readers
        see either the old file or the new one, never a half-written
        config that would refuse to load on the next start.
        """
        text = config_mod.render(values)
        temp: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=self._path.parent,
                    prefix=f".{self._path.name}.", suffix=".tmp",
                    delete=False) as handle:
                temp = Path(handle.name)
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self._path)
        except OSError as e:
            if temp is not None:
                temp.unlink(missing_ok=True)
            raise ConfigError(f"could not write {self._path}: {e}") from e
