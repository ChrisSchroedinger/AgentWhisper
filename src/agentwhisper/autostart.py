"""Start-at-login via XDG autostart (~/.config/autostart).

Chosen over a systemd user unit deliberately: an XDG autostart entry is
started by the desktop session itself, so DISPLAY/XAUTHORITY are always
right — no environment-import dance. Works on every XDG-compliant
desktop, XFCE included.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def autostart_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "autostart" / "agentwhisper.desktop"


def daemon_command() -> str:
    """The command the session should run: the stable launcher if it is
    on PATH, otherwise the exact binary running right now."""
    return shutil.which("agentwhisperd") or str(Path(sys.argv[0]).resolve())


def is_enabled(path: Path | None = None) -> bool:
    return (path or autostart_path()).exists()


def enable(path: Path | None = None, command: str | None = None) -> None:
    path = path or autostart_path()
    command = command or daemon_command()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=AgentWhisper\n"
        "Comment=Push-to-talk voice dictation\n"
        f"Exec={command}\n"
        "Icon=agentwhisper\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-Delay=3\n"
    )


def disable(path: Path | None = None) -> None:
    (path or autostart_path()).unlink(missing_ok=True)
