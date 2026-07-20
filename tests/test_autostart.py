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


def test_an_unwritable_entry_is_reported_not_raised(monkeypatch, tmp_path):
    """GTK swallows what a menu handler raises, so a failed write has to
    come back as False — otherwise the checkbox stays ticked while
    nothing was saved."""
    from tests.test_daemon import _FakeDesktop, _FakeEngine

    from agentwhisper.config import Config
    from agentwhisper.daemon import Daemon
    from agentwhisper.settings import Settings

    def refuse(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(autostart, "enable", refuse)
    daemon = Daemon(Settings(Config(), tmp_path / "config.toml"),
                    engine=_FakeEngine(), desktop=_FakeDesktop())
    assert daemon.set_autostart(True) is False
