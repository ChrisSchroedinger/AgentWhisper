# AgentWhisper

Rock-solid push-to-talk voice dictation for Linux. Hold a key, speak,
release — the transcript lands in your clipboard and (optionally) is
typed into the focused window. Local, offline, private.

Successor to soupawhisper, redesigned from scratch as a **daemon +
thin clients** architecture. See [DESIGN.md](DESIGN.md) for the full
design and rationale.

**Status: early development — not yet usable.**

## Development

```bash
uv sync          # create env, install deps
uv run pytest    # run tests
uv run ruff check .
```
