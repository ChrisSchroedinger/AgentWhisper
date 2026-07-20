# AgentWhisper — Design Document

> Status: **draft for discussion** — v0.1, 2026-07-04
> Successor to soupawhisper, built from scratch around its lessons.

## Vision

**v1: rock-solid push-to-talk dictation for Linux.** Speak, release, text
appears — every time, with no mystery failures. The architecture leaves
a clean seam for a future "agent mode" (speech → LLM → action), which is
where the name points, but v1 ships dictation only.

## Decisions (settled)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scope v1 | Dictation only | Do one thing perfectly; agent mode is a future client, not a v1 feature |
| Platform | X11 now, Wayland-ready | Debian/Ubuntu + XFCE = X11 for years; all display code behind one interface |
| Stack | Python 3.11+, uv, src/ layout | Fastest iteration for a solo project; uv kills the venv/packaging pain |
| STT | Pluggable engine, local faster-whisper first | Private/offline v1; cloud or agent engines drop in later |

## Lessons from soupawhisper (the "never again" list)

1. **No monolith.** 700 lines in one file made every fix risky. →
   Small modules, single responsibilities, unit tests.
2. **No invisible runtime failures.** pystray silently picked a dead
   backend; the venv silently hid GTK bindings. → Verify every
   integration at startup and **fail loudly** with an actionable message.
3. **No accidental multi-instance.** → The daemon's socket *is* the
   single-instance lock, by construction.
4. **No scattered desktop glue.** → One `DesktopBackend` interface owns
   typing, clipboard, and notifications. X11 implementation first;
   a Wayland one later is a new module, not a rewrite.

## Architecture: daemon + thin CLI client

```
┌─────────────────────────────────────────────────┐
│ agentwhisperd (systemd user service)            │
│                                                 │
│  hotkey listener ─▶ state machine ─▶ engine     │
│  (pynput/X11)       (record/idle)    (whisper)  │
│         │                 │             │       │
│         ▼                 ▼             ▼       │
│  audio capture      DesktopBackend (X11):      │
│  (sounddevice)      type / clipboard / notify   │
│                                                 │
│  IPC server: unix socket, JSON-lines protocol   │
└───────▲──────────────▲──────────────▲───────────┘
        │              │              │
   agentwhisper    tray client    (future: agent
   CLI (status,    (StatusNotifier) client, GUI)
   toggle, logs)
```

- **Daemon** owns all state: audio, model, recording lifecycle. It runs
  headless; a machine with no panel still dictates perfectly.
- **IPC**: Unix socket at `$XDG_RUNTIME_DIR/agentwhisper.sock`,
  newline-delimited JSON. Simple to test with `nc`, no D-Bus library
  dependency. Binding the socket doubles as the single-instance lock.
- **CLI client** (`agentwhisper status|toggle|start|stop|set|logs`) is
  the first client and the debugging story.
- **Tray** is optional, not a core feature. If it can't get an
  AppIndicator backend it logs why and the daemon keeps running
  headless.

## v1 feature list

- **English-only** (decided 2026-07-04, superseded in v0.4.1): v1
  offered only the `*.en` models to remove the model/language-mismatch
  class of bugs. Since v0.4.1 only the general multilingual models are
  offered and no language is pinned — Whisper recognizes whatever is
  spoken, so the mismatch class of bugs stays removed with zero config.
  Old `*.en` config values are normalized to the general model on load.
- Hold-to-record and tap-to-toggle modes (configurable hotkey, F12
  default), switchable live from the tray menu and `agentwhisper mode`
- The hotkey is reserved **exclusively** (XGrabKey): no collisions with
  other applications' F12 bindings while the daemon runs
- Debounced against X11 auto-repeat (carry over the 180 ms fix)
- Recording OSD: semi-transparent popup bottom-center (~15% above the
  edge) with green equalizer bars following the live mic level
- Local faster-whisper engine; model configurable
- Output: clipboard always; auto-type into the focused window (toggleable)
- Target-window mode (session-only): all dictations typed into one
  chosen window + submitted with Enter — the hands-free step toward
  agent mode
- Cancel gesture: Esc discards an active recording; Esc is grabbed
  only while recording, untouched otherwise
- Desktop notifications for state changes (toggleable)
- Tray icon with menu (toggle, model, quit)
- `agentwhisper` CLI for everything the tray does, plus `status` and `logs`
- Startup self-check: audio device, X11 tools, model availability —
  every failure explains its fix
- Hard cap on recording length; stale temp cleanup

## Technical choices

| Concern | Choice | Notes |
|---------|--------|-------|
| Audio capture | `sounddevice` (PortAudio) | Native, in-process; device selection + level metering become possible. No more arecord shell-out. |
| Hotkey | `python-xlib` XGrabKey | Exclusive system-wide grab: the key never reaches other apps while the daemon runs. BadAccess (someone else grabbed it) is a clear error. evdev is the future Wayland path |
| Typing/clipboard | xdotool/xclip subprocess **inside** the X11 backend | Proven; verified at startup; isolated so it's swappable |
| Config | TOML at `~/.config/agentwhisper/config.toml`, stdlib `tomllib`, dataclass-validated | No pydantic dependency for v1 |
| Settings changes | One `Settings.change()`: validate, write atomically, notify — all-or-nothing | See below. Callers used to assign a field, save, and remember to update whatever else held a copy |
| Model residency | The engine owns it: weights are dropped after `unload_after_seconds` idle and reloaded when recording starts | See below — the daemon never asks whether the model is in memory |
| Engine state | `EngineStatus(phase, percent, error)`, a frozen dataclass — not a free-text string | Callers compare phases; the wording is written where it is displayed. The string version was parsed back apart by three modules |
| Logging | `logging` → file + stderr (journald picks it up) | `agentwhisper logs` tails it |
| Tests | pytest; unit tests for state machine, debounce, config, protocol; integration test with a fake engine + fake backend | The state machine is pure logic — fully testable without audio or X11 |
| Lint/format | ruff (lint + format) | One tool |
| Packaging | uv project; `install.sh` that installs uv if needed, creates the env, installs the systemd user unit + .desktop | .deb comes later, once v1 is stable — packaging a moving target is how soupawhisper got hurt |

## Repository layout

```
agentwhisper/
├── pyproject.toml            # uv-managed; deps, ruff, pytest config
├── DESIGN.md                 # this file
├── README.md
├── CHANGELOG.md
├── install.sh
├── src/agentwhisper/
│   ├── __init__.py           # version
│   ├── config.py             # the values, their rules, the TOML file
│   ├── settings.py           # the one place a setting changes
│   ├── state.py              # recording state machine (pure logic)
│   ├── audio.py              # sounddevice capture → wav buffer
│   ├── hotkey.py             # key listener → events (debounce lives here)
│   ├── engines/
│   │   ├── base.py           # Engine protocol: transcribe(audio) -> text
│   │   └── whisper_local.py  # faster-whisper implementation
│   ├── desktop/
│   │   ├── base.py           # DesktopBackend protocol: type/copy/notify
│   │   └── x11.py            # xdotool/xclip/notify-send implementation
│   ├── ipc.py                # socket protocol (shared by daemon & clients)
│   ├── daemon.py             # wires everything; the service entry point
│   ├── cli.py                # client commands
│   └── tray.py               # tray client
├── packaging/                # systemd unit, .desktop, icons
└── tests/
```

## Milestones (step by step, each one usable and tested)

1. **Starts and shows up** ✅: daemon skeleton (config, logging,
   socket = single-instance lock, CLI `status/toggle/quit`), tray icon
   in the XFCE panel via direct GTK/AyatanaAppIndicator bindings (no
   pystray backend guessing), XFCE menu entry, user-level `install.sh`.
   For this milestone the tray runs inside the daemon process; the
   split into a separate tray client happens once the IPC surface has
   settled.
2. **Hears** ✅: audio capture (sounddevice), exclusive XGrabKey hotkey
   wired to the state machine, recording visible in tray + `status` +
   the OSD level visualizer, mode switching in the tray menu.
3. **Transcribes** ✅: Engine interface + faster-whisper implementation
   (background load at startup), clipboard via the X11 DesktopBackend.
4. **Types** ✅: auto-type (xdotool --clearmodifiers) + notifications
   (notify-send with the replace-don't-stack hint) via the X11
   DesktopBackend; Auto-Type/Notifications toggles in the tray menu.
5. **Hardens** ✅: start-at-login via XDG autostart (chosen over a
   systemd unit: the session starts it, so DISPLAY is always right),
   guided first-run model download (downloading/loading/ready surfaced
   in tray + notifications), `.deb` packaging (build-deb.sh; venv in
   postinst, same pattern as install.sh).
6. **AppImage** (planned): a single-file, distro-independent build.
   Open question to solve: bundling Python + the GTK/AppIndicator
   bindings that the venv approach borrows from the system.

## Model residency (v0.4.2)

The model weights are the only large thing the daemon holds — 140 MB for
`base`, 460 MB for `small`, up to 3 GB for `large-v3` — and a
push-to-talk tool is idle almost all of the time. So residency is a
policy that lives entirely inside `engines/whisper_local.py`, behind the
unchanged `transcribe()` seam: no caller ever asks whether the weights
are in memory, and `status` keeps reporting `ready` while they are not.

- **Unload** after `whisper.unload_after_seconds` idle (default 300, `0`
  disables). `ctranslate2`'s `unload_model(to_cpu=False)` frees the
  weights, but glibc keeps the arenas — `malloc_trim(0)` is what
  actually returns the pages. Measured on `small`: 687 MB → 420 MB after
  the free, → 173 MB after the trim. Skipping the trim gives up two
  thirds of the win.
- **Reload on recording start**, not on transcription: the daemon
  spawns `engine.warm_up()` from `_start_recording`, so the reload
  (~0.3 s for `base`, ~1.0 s for `small`) overlaps the user speaking.
  Measured cost of a 3 s dictation from cold: ±0.05 s, i.e. nothing. The
  residual only shows up on a dictation shorter than the reload, and
  only on the first one after an idle period.
- **A `threading.RLock` is held across every use of the weights**, so
  the idle timer can never unload them mid-transcription — ctranslate2
  raises `No model replica is available in this thread` if it does, and
  there is no lazy-reload path to catch it.

## Changing a setting (v0.5.2)

`config.py` says what a valid config *is*; `settings.py` owns changing
one. Every change — tray menu, CLI, IPC — goes through
`Settings.change(**updates)`, which does three things in order and stops
at the first that refuses:

1. **Validate the whole config with the change applied.** `Config.validate()`
   is the single gate, so the range checks the file is held to are the
   ones the tray and the CLI are held to. It checks types as well as
   ranges: values arriving from a socket never met the TOML parser.
2. **Write atomically** — temporary file in the same directory, `fsync`,
   `os.replace`. A full disk or a crash leaves the previous config
   intact instead of a truncated file that refuses to load next start.
3. **Notify subscribers.** State that mirrors a setting is refreshed
   from here rather than by the caller. The state machine's `mode` is
   the only such copy today, and it now moves only once the new value is
   actually on disk.

Because nothing changes unless all three succeed, a failure is reportable:
the daemon's setters return `False`, notify the user, and the tray puts
the menu item back where it was. Previously a failed save raised inside
a GTK callback, which swallows it — the checkbox showed a setting that
was never stored.

Deliberately **not** persisted: the Enabled toggle. Disabling dictation
is a "not right now" action; starting up silently deaf after a reboot
would be a worse bug than the inconsistency.

## Future seams (explicitly designed for, not built)

- **Languages beyond English**: ✅ shipped in v0.4.1 — simpler than the
  planned seam: only the general multilingual models are offered and no
  `language` option exists; Whisper handles the spoken language itself.
- **Agent mode**: a new Engine that sends transcripts to an LLM and a
  new client that renders/executes responses. The daemon doesn't change.
- **Wayland**: `desktop/wayland.py` + an evdev hotkey listener.
- **Cloud STT**: another Engine implementation behind a config flag.

## Resolved questions (2026-07-04)

1. **Default model: `base.en`** (small, fast). v1 is English-only, so
   the language/model mismatch trap does not exist by construction;
   the config layer rejects multilingual models until languages land.
   *(Since v0.4.1 the default is `base` — see the superseded note above.)*
2. **No autostart during development.** Manual start (menu /
   `systemctl --user start agentwhisper`) while we iterate; autostart
   ships when v1 is trusted.
3. **Fresh icon design** — mic + spark/agent motif, distinguishable
   from soupawhisper in the panel during the transition.
