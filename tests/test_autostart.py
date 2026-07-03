from agentwhisper import autostart


def test_enable_disable_roundtrip(tmp_path):
    p = tmp_path / "autostart" / "agentwhisper.desktop"
    assert not autostart.is_enabled(p)
    autostart.enable(p, command="/usr/bin/agentwhisperd")
    assert autostart.is_enabled(p)
    content = p.read_text()
    assert "Exec=/usr/bin/agentwhisperd" in content
    assert "[Desktop Entry]" in content
    autostart.disable(p)
    assert not autostart.is_enabled(p)


def test_disable_when_absent_is_fine(tmp_path):
    autostart.disable(tmp_path / "nope.desktop")


def test_enable_is_idempotent(tmp_path):
    p = tmp_path / "agentwhisper.desktop"
    autostart.enable(p, command="x")
    autostart.enable(p, command="y")
    assert "Exec=y" in p.read_text()


def test_daemon_command_resolves_to_something():
    assert autostart.daemon_command()
