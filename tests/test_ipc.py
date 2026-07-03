import pytest

from agentwhisper import ipc


def test_encode_decode_roundtrip():
    message = {"cmd": "set", "key": "language", "value": "de"}
    assert ipc.decode(ipc.encode(message).rstrip(b"\n")) == message


def test_encode_is_single_line():
    line = ipc.encode({"cmd": "status", "note": "with\nnewline"})
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1  # embedded newline is escaped by JSON


def test_decode_rejects_garbage():
    with pytest.raises(ipc.ProtocolError):
        ipc.decode(b"not json{")


def test_decode_rejects_non_object():
    with pytest.raises(ipc.ProtocolError):
        ipc.decode(b"[1,2,3]")


def test_decode_rejects_oversized():
    huge = ipc.encode({"x": "a" * ipc.MAX_LINE_BYTES})
    with pytest.raises(ipc.ProtocolError):
        ipc.decode(huge)


def test_ok_and_error_shapes():
    assert ipc.ok(phase="idle") == {"ok": True, "phase": "idle"}
    assert ipc.error("nope") == {"ok": False, "error": "nope"}


def test_socket_path_prefers_xdg(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert str(ipc.socket_path()) == "/run/user/1000/agentwhisper.sock"
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert "agentwhisper-" in str(ipc.socket_path())
