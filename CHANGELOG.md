# Changelog

All notable changes to AgentWhisper are documented here.

## 0.5.0 — 2026-07-20

### Added
- `whisper.unload_after_seconds` config key: idle period after which the
  model weights are released, in seconds. Accepts `0` (never unload,
  the pre-0.5.0 behaviour) or `30`–`3600`. Defaults to `300`.
- `Engine.warm_up()` in the engine protocol: a blocking call that makes
  the engine ready to transcribe. A no-op is a valid implementation;
  `transcribe()` remains correct whether or not it is called.
- `tests/test_residency.py`: 10 tests covering the unload/reload cycle,
  the no-op paths, and the lock that prevents a concurrent unload.

### Changed
- The model weights are now released after `unload_after_seconds` of
  inactivity and reloaded when recording starts, rather than staying
  resident for the process lifetime. Idle RSS drops from 285 MB to
  184 MB with `base`, and from 687 MB to 173 MB with `small`.
- Residency is internal to `WhisperLocalEngine`. `Engine.status` still
  reports `ready` while the weights are unloaded, and `transcribe()`
  reloads them if needed, so no caller observes the change.
- The daemon calls `Engine.warm_up()` on a background thread from
  `_start_recording()`, overlapping the reload (~0.3 s for `base`,
  ~1.0 s for `small`) with the recording. Measured end-to-end cost of a
  3 s dictation against unloaded weights: within noise of the resident
  case for both models.

### Notes
- `ctranslate2.models.Whisper.unload_model()` frees the weights but
  glibc retains the arenas, so RSS barely moves; `malloc_trim(0)` is
  issued after the unload to return the pages. Measured with `small`:
  687 MB resident, 420 MB after the free, 173 MB after the trim. The
  call is skipped on platforms without glibc.
- A re-entrant lock is held for the duration of every use of the
  weights. `ctranslate2` has no lazy-reload path and raises
  `RuntimeError: No model replica is available in this thread` if the
  weights are released mid-transcription.

## 0.4.1 — 2026-07-19

### Changed
- AgentWhisper now understands 90+ languages, not just English. The
  model list switched from the English-only `*.en` variants to the
  general Whisper models (`tiny`, `base`, `small`, `medium`,
  `large-v3`, `large-v3-turbo`), and no transcription language is
  pinned anymore: just speak, whatever the language. Nothing to
  configure. Existing configs naming a `*.en` model are picked up as
  the matching general model automatically (expect a one-time
  download of it on first use). The default model is now `base`.

## 0.4.0 — 2026-07-09

### Added
- Cancel a recording with **Esc**: changed your mind mid-dictation?
  Press Escape and the recording is discarded — nothing is transcribed
  or typed. Esc is reserved only while a recording is running; the
  rest of the time it reaches your applications untouched. Also
  available as `agentwhisper cancel`.

(0.4.0 rather than 0.3.11: version components cap at 9 and roll over.)

## 0.3.10 — 2026-07-09

### Changed
- Picking the dictation target is now visual: tray → *Choose active
  window…* opens a grid of your open windows (with their icons) —
  click the one you want instead of aiming a crosshair at it. The
  crosshair way lives on in `agentwhisper target choose`.
- Dictating into a chosen window no longer brings it to the front. The
  text is delivered in the background: the target borrows the keyboard
  only for the moment of typing, then focus returns to the window you
  were working in — made for talking to an AI agent in a side window
  while you keep working. (Avoid typing during that split second; the
  keys would land in the target window.)

## 0.3.9 — 2026-07-09

### Added
- Dictate into one window: click any window once (tray → *Dictate into
  one window…*, or `agentwhisper target choose`) and from then on every
  dictation is typed into that window and submitted with Enter — no
  matter which window is focused. Made for talking to an AI agent in a
  terminal while you work elsewhere. The window is raised each time,
  the clipboard still gets a copy of every dictation, and if the
  chosen window closes, AgentWhisper says so and goes back to normal
  typing. The choice lasts until you clear it or quit (window ids
  don't survive restarts, so it is not saved to config.toml).

## 0.3.8 — 2026-07-09

### Added
- The recording limit (the safety cap that stops a stuck key from
  recording forever) can now be changed without editing config.toml:
  tray menu → *Recording Limit* (presets from 30 seconds to 10 minutes;
  a hand-edited custom value keeps its own entry) or
  `agentwhisper limit <seconds>`. Changes apply from the next recording
  and are saved to config.toml. `agentwhisper status` now shows the
  current limit.

### Changed
- `max_record_seconds` is now validated to the range 30–600 seconds
  (was: any positive integer) — everywhere: config.toml, the tray menu,
  and the CLI. An out-of-range value in a hand-edited config is
  rejected at startup with a message saying the allowed range.

## 0.3.7 — 2026-07-04

### Changed
- `config.toml` now documents every setting inline: possible values,
  meanings, model size/speed trade-offs. The explanations survive
  settings changes made from the tray menu (previously a tray change
  rewrote the file without comments).

## 0.3.6 — 2026-07-04

### Fixed
- The tray status line could show "Ready" during the model download
  while `agentwhisper status` correctly said "downloading": the label
  was rendered before the download began and its refresh loop exited
  on a startup race. The refresh now runs until the model has actually
  finished loading, and the pre-download moment shows "Preparing
  speech model…" instead of "Ready".

## 0.3.5 — 2026-07-04

### Added
- Live download progress for the speech model: the tray status line
  shows "Downloading speech model… 47% (one time)" and `agentwhisper
  status` shows `engine: downloading 47%`. Measured from bytes on disk
  against the model's real size, so resumed downloads report correctly
  too.

## 0.3.4 — 2026-07-04

### Fixed
- After quitting mid-download, a restart claimed "Preparing speech
  model" instead of "Downloading": the cache check only looked for the
  model's directory, which a partial download already creates. The app
  now verifies the model is completely downloaded, so the resumed
  download is labeled (and notified) as a download again.

## 0.3.3 — 2026-07-04

### Fixed
- Quitting during the model download left a zombie process with a
  frozen tray icon (the downloader's worker threads kept the dead
  daemon alive), and a restart then showed two icons. The daemon now
  terminates for real after cleanup — the interrupted download simply
  resumes on the next start — and the tray icon unregisters itself the
  moment you quit.

## 0.3.2 — 2026-07-04

### Changed
- Quiet `.deb` installation: pip's download log no longer scrolls by.
  The postinst prints a few concise progress lines; real errors still
  show.

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
