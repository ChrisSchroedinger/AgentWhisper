"""agentwhisperd — the daemon.

Milestone 2 scope: the daemon HEARS.
- the hotkey is reserved system-wide via XGrabKey (no collisions with
  other apps' F12 bindings)
- press/release drive the debounced state machine; recording is real
  microphone capture (sounddevice)
- recording state is visible: red tray icon + the OSD level visualizer
- hold/toggle mode switchable from the tray menu or `agentwhisper mode`

Transcription lands in milestone 3 — captured audio is measured,
logged, and discarded.
"""

from __future__ import annotations

import logging
import os
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

from agentwhisper import __version__, ipc
from agentwhisper import config as config_mod
from agentwhisper.audio import AudioError, Recorder
from agentwhisper.state import RELEASE_DEBOUNCE_SECONDS, Action, DictationStateMachine

log = logging.getLogger("agentwhisper")

LOG_DIR = Path.home() / ".local" / "state" / "agentwhisper"
LOG_PATH = LOG_DIR / "daemon.log"


class Daemon:
    """Wires hotkey events through the state machine to real effects."""

    def __init__(self, cfg: config_mod.Config):
        self.config = cfg
        self.sm = DictationStateMachine(mode=cfg.mode)
        self.recorder = Recorder()
        self.started_at = time.time()
        self.hotkey_status = "inactive"
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._tray = None
        self._visualizer = None
        self._settle_timer: threading.Timer | None = None
        self._max_timer: threading.Timer | None = None

    # -- hotkey events (called from the listener thread) -----------------

    def on_hotkey_press(self) -> None:
        with self._lock:
            self._dispatch(self.sm.key_pressed())

    def on_hotkey_release(self) -> None:
        with self._lock:
            self._dispatch(self.sm.key_released())

    def _on_settle_timer(self) -> None:
        with self._lock:
            self._dispatch(self.sm.release_settled())

    def _on_max_duration(self) -> None:
        log.warning("recording hit the %ds cap; stopping",
                    self.config.max_record_seconds)
        with self._lock:
            self._dispatch(self.sm.max_duration_reached())

    # -- state machine actions → real effects ----------------------------

    def _dispatch(self, actions: list[Action]) -> None:
        for action in actions:
            if action is Action.START_RECORDING:
                self._start_recording()
            elif action is Action.STOP_RECORDING:
                self._stop_recording(discard=False)
            elif action is Action.ABORT_RECORDING:
                self._stop_recording(discard=True)
            elif action is Action.SCHEDULE_SETTLE:
                self._cancel_timer("_settle_timer")
                self._settle_timer = threading.Timer(
                    RELEASE_DEBOUNCE_SECONDS, self._on_settle_timer)
                self._settle_timer.start()
            elif action is Action.CANCEL_SETTLE:
                self._cancel_timer("_settle_timer")

    def _start_recording(self) -> None:
        try:
            self.recorder.start()
        except AudioError as e:
            log.error("%s", e)
            self._dispatch(self.sm.max_duration_reached())  # back to idle
            return
        log.info("recording started")
        self._max_timer = threading.Timer(
            self.config.max_record_seconds, self._on_max_duration)
        self._max_timer.start()
        if self._tray is not None:
            self._tray.set_recording(True)
        if self._visualizer is not None:
            self._visualizer.show()

    def _stop_recording(self, discard: bool) -> None:
        self._cancel_timer("_max_timer")
        samples, duration = self.recorder.stop()
        if self._visualizer is not None:
            self._visualizer.hide()
        if self._tray is not None:
            self._tray.set_recording(False)
        if discard:
            log.info("recording aborted (%.1fs discarded)", duration)
        else:
            log.info("recording stopped: %.1fs captured (%d samples). "
                     "Transcription arrives in milestone 3 — discarding.",
                     duration, len(samples))
        # No engine yet: close the transcribing phase immediately.
        self._dispatch(self.sm.transcription_finished())

    def _cancel_timer(self, name: str) -> None:
        timer = getattr(self, name)
        if timer is not None:
            timer.cancel()
            setattr(self, name, None)

    # -- interface used by the tray ---------------------------------------

    def is_enabled(self) -> bool:
        return self.sm.enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._dispatch(self.sm.set_enabled(enabled))
        log.info("dictation %s", "enabled" if enabled else "disabled")

    def get_mode(self) -> str:
        return self.sm.mode

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._dispatch(self.sm.set_mode(mode))
            self.config.mode = mode
        config_mod.save(self.config)
        log.info("mode set to %s", mode)

    def hotkey_name(self) -> str:
        return self.config.hotkey

    def quit(self) -> None:
        log.info("shutdown requested")
        with self._lock:
            self._dispatch(self.sm.shutdown())
        self._shutdown.set()
        if self._tray is not None:
            self._tray.stop()

    # -- IPC ----------------------------------------------------------------

    def handle_request(self, message: dict) -> dict:
        cmd = message.get("cmd")
        if cmd == "ping":
            return ipc.ok()
        if cmd == "status":
            return ipc.ok(
                version=__version__,
                phase=self.sm.phase.name.lower(),
                enabled=self.sm.enabled,
                model=self.config.model,
                mode=self.sm.mode,
                hotkey=self.config.hotkey,
                hotkey_status=self.hotkey_status,
                tray="active" if self._tray is not None else "unavailable",
                visualizer="active" if self._visualizer is not None else "unavailable",
                uptime_seconds=round(time.time() - self.started_at),
                pid=os.getpid(),
            )
        if cmd == "toggle-enabled":
            self.set_enabled(not self.sm.enabled)
            return ipc.ok(enabled=self.sm.enabled)
        if cmd == "set-mode":
            mode = message.get("mode")
            if mode not in ("hold", "toggle"):
                return ipc.error(f"mode must be 'hold' or 'toggle', not {mode!r}")
            self.set_mode(mode)
            return ipc.ok(mode=mode)
        if cmd == "quit":
            # Reply first, then shut down, so the client gets its answer.
            threading.Timer(0.1, self.quit).start()
            return ipc.ok(quitting=True)
        return ipc.error(f"unknown command {cmd!r}")


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(ipc.MAX_LINE_BYTES + 1)
        if not line:
            return
        try:
            request = ipc.decode(line.rstrip(b"\n"))
            response = self.server.daemon.handle_request(request)  # type: ignore[attr-defined]
        except ipc.ProtocolError as e:
            response = ipc.error(str(e))
        except Exception:
            log.exception("error handling request")
            response = ipc.error("internal error (see daemon log)")
        self.wfile.write(ipc.encode(response))


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, daemon: Daemon):
        self.daemon = daemon
        super().__init__(path, _Handler)


def _claim_socket(path: Path) -> None:
    """Ensure we can bind: remove a stale socket, or exit if one is live."""
    if not path.exists():
        return
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(1.0)
        probe.connect(str(path))
    except OSError:
        log.info("removing stale socket %s", path)
        path.unlink()
        return
    finally:
        probe.close()
    print(
        "agentwhisperd is already running (socket in use).\n"
        "Check it with: agentwhisper status",
        file=sys.stderr,
    )
    sys.exit(1)


def _setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stderr)],
    )


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(f"agentwhisperd {__version__}")
        return 0

    _setup_logging()
    log.info("agentwhisperd %s starting", __version__)

    config_mod.write_default()
    try:
        cfg = config_mod.load()
    except config_mod.ConfigError as e:
        log.error("configuration invalid:\n%s", e)
        return 2
    log.info("config OK: model=%s mode=%s hotkey=%s", cfg.model, cfg.mode, cfg.hotkey)

    daemon = Daemon(cfg)

    sock_path = ipc.socket_path()
    _claim_socket(sock_path)
    server = _Server(str(sock_path), daemon)
    server_thread = threading.Thread(target=server.serve_forever, name="ipc", daemon=True)
    server_thread.start()
    log.info("IPC socket listening at %s", sock_path)

    # Reserve the hotkey system-wide. A grab failure is fatal only if it
    # is a conflict the user must resolve; a missing DISPLAY just means
    # a headless session (still controllable via the CLI).
    from agentwhisper.hotkey import HotkeyError, X11HotkeyListener

    listener = X11HotkeyListener(cfg.hotkey, daemon.on_hotkey_press,
                                 daemon.on_hotkey_release)
    try:
        listener.start()
        daemon.hotkey_status = "grabbed (exclusive)"
        log.info("hotkey %s reserved system-wide (XGrabKey)", cfg.hotkey.upper())
    except HotkeyError as e:
        daemon.hotkey_status = f"unavailable: {e}"
        log.error("hotkey unavailable: %s", e)

    exit_code = 0
    try:
        from agentwhisper.tray import TrayUnavailable, create_tray

        try:
            daemon._tray = create_tray(daemon)
            log.info("tray icon active (AyatanaAppIndicator)")
        except TrayUnavailable as e:
            log.warning("tray unavailable: %s", e)
            log.warning("running headless; control with: agentwhisper status|toggle|quit")

        if daemon._tray is not None:
            from agentwhisper.visualizer import Visualizer, VisualizerUnavailable

            try:
                daemon._visualizer = Visualizer(lambda: daemon.recorder.level)
                log.info("recording visualizer ready")
            except VisualizerUnavailable as e:
                log.warning("visualizer unavailable: %s", e)
            daemon._tray.run()  # blocks until quit
        else:
            _wait_headless(daemon)
    finally:
        listener.stop()
        server.shutdown()
        server.server_close()
        sock_path.unlink(missing_ok=True)
        log.info("agentwhisperd stopped")
    return exit_code


def _wait_headless(daemon: Daemon) -> None:
    import signal

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: daemon.quit())
    daemon._shutdown.wait()


if __name__ == "__main__":
    sys.exit(main())
