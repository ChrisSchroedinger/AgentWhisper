"""X11 desktop backend: clipboard (xclip), typing (xdotool), and
notifications (notify-send) — all verified at startup by check()."""

from __future__ import annotations

import os
import shutil
import subprocess

from agentwhisper.desktop.base import DesktopError

_TOOLS = {
    "xclip": "clipboard",
    "xdotool": "auto-typing",
    "notify-send": "notifications (package: libnotify-bin)",
}


class X11Desktop:
    def check(self) -> list[str]:
        problems = []
        if not os.environ.get("DISPLAY"):
            problems.append("no DISPLAY: desktop features need a graphical X11 session")
        for tool, purpose in _TOOLS.items():
            if shutil.which(tool) is None:
                problems.append(
                    f"{tool} is not installed ({purpose} will fail) — "
                    f"fix: sudo apt install xclip xdotool libnotify-bin"
                )
        return problems

    def copy(self, text: str) -> None:
        try:
            # xclip forks a background child that owns the selection and
            # inherits our fds. Any PIPE here would be held open by that
            # child, blocking run() until the timeout — so no pipes at all.
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode(),
                timeout=5,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as e:
            raise DesktopError("xclip is not installed — sudo apt install xclip") from e
        except subprocess.CalledProcessError as e:
            raise DesktopError(f"xclip failed (exit {e.returncode})") from e
        except subprocess.TimeoutExpired as e:
            raise DesktopError("xclip timed out taking the clipboard") from e

    def type_text(self, text: str) -> None:
        # --clearmodifiers: the user may still be touching the hotkey;
        # don't let a held modifier mangle the text. Timeout scales with
        # length (xdotool types ~80 chars/s at its default delay).
        timeout = 10 + len(text) / 40
        try:
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--", text],
                timeout=timeout,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise DesktopError("xdotool is not installed — sudo apt install xdotool") from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode(errors="replace").strip()
            raise DesktopError(f"xdotool failed: {stderr or e}") from e
        except subprocess.TimeoutExpired as e:
            raise DesktopError("xdotool timed out while typing") from e

    def notify(self, summary: str, body: str = "") -> None:
        try:
            # The synchronous hint makes each notification REPLACE the
            # previous one instead of stacking — rapid dictations stay calm.
            subprocess.run(
                ["notify-send", "-a", "AgentWhisper", "-i", "agentwhisper",
                 "-t", "3000",
                 "-h", "string:x-canonical-private-synchronous:agentwhisper",
                 summary, body],
                timeout=5,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise DesktopError(
                "notify-send is not installed — sudo apt install libnotify-bin") from e
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise DesktopError(f"notify-send failed: {e}") from e
