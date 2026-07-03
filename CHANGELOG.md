# Changelog

All notable changes to AgentWhisper are documented here.

## 0.3.1 — 2026-07-04

### Fixed
- The `.deb` install printed alarming (but harmless) pip dependency
  errors about unrelated system packages: with system-site-packages,
  pip cross-checks apps that never see AgentWhisper's private
  virtualenv. Suppressed with `--no-warn-conflicts` — our own
  dependency set is resolved consistently from the lockfile.

## 0.3.0 — 2026-07-04

### Added
- **Start at login**: new tray checkbox and `agentwhisper autostart on|off`
  (XDG autostart entry, works on any desktop).
- **Friendly first-run experience**: the app now tells you when the
  speech model is downloading (one-time), when it's ready, and — if you
  dictate too early — that your dictation is queued. The tray status
  line shows the model state; a cached model is detected and loads
  without any download notice.
- **`.deb` package**: `./build-deb.sh` produces
  `dist/agentwhisper_<version>_all.deb` as an alternative, system-wide
  install method (dependencies installed into a private virtualenv at
  package configure time).

### Known limitations
- English only, X11 only (both designed-for future steps)

## 0.2.0 — 2026-07-04

First deployable release. Complete push-to-talk dictation on X11/XFCE,
verified in daily use on Debian/Ubuntu.

### Added
- **Daemon + clients architecture**: `agentwhisperd` owns all state; the
  Unix socket doubles as the single-instance lock. CLI client
  (`agentwhisper status|toggle|mode|quit`) for everything the tray does.
- **Exclusive system-wide hotkey** (X11 XGrabKey, F12 default): other
  apps never see the key while the daemon runs; Ctrl/Alt+F12 bindings
  elsewhere keep working. Grab conflicts are clear, actionable errors.
- **Two recording modes**, switchable live from the tray or CLI:
  hold-to-talk and press-to-toggle. Debounced against X11 auto-repeat.
- **Recording OSD**: semi-transparent popup near the bottom of the
  screen with green equalizer bars following the live microphone level.
- **Local transcription** (faster-whisper, English): model loads in the
  background at startup; first run downloads it to the shared
  Hugging Face cache.
- **Delivery**: clipboard always, auto-typing into the focused window
  (toggleable); a typing failure never loses the text.
- **Notifications** with transcript preview; replace instead of stack.
- **Tray icon** via direct GTK/AyatanaAppIndicator bindings; red icon
  while recording, live status line in the menu.
- **Self-checking startup**: config validation, desktop-tool checks,
  engine status — every failure names its fix. Logs at
  `~/.local/state/agentwhisper/daemon.log`.
- User-level `install.sh` / `uninstall.sh` (no sudo), XFCE menu entry.
- 53 automated tests (state machine, config, IPC, full pipeline).

### Known limitations
- English only (multilingual is a designed-for future step)
- X11 only (Wayland is a designed-for future step)
- No autostart on login yet (milestone 5)
