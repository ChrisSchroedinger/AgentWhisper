"""IPC protocol shared by the daemon and all clients.

Transport: Unix stream socket at $XDG_RUNTIME_DIR/agentwhisper.sock.
Wire format: one JSON object per line (newline-delimited), UTF-8.

Requests:  {"cmd": "status"} or {"cmd": "set", "key": ..., "value": ...}
Responses: {"ok": true, ...payload} or {"ok": false, "error": "..."}

Binding the socket is also the daemon's single-instance lock: a second
daemon fails to bind and exits, by construction.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SOCKET_NAME = "agentwhisper.sock"
MAX_LINE_BYTES = 64 * 1024


class ProtocolError(Exception):
    pass


def socket_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / SOCKET_NAME
    return Path(f"/tmp/agentwhisper-{os.getuid()}.sock")


def encode(message: dict) -> bytes:
    line = json.dumps(message, separators=(",", ":")).encode()
    if b"\n" in line:
        raise ProtocolError("message must serialize to a single line")
    return line + b"\n"


def decode(line: bytes) -> dict:
    if len(line) > MAX_LINE_BYTES:
        raise ProtocolError(f"message exceeds {MAX_LINE_BYTES} bytes")
    try:
        message = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"invalid JSON: {e}") from e
    if not isinstance(message, dict):
        raise ProtocolError("message must be a JSON object")
    return message


def ok(**payload) -> dict:
    return {"ok": True, **payload}


def error(message: str) -> dict:
    return {"ok": False, "error": message}
