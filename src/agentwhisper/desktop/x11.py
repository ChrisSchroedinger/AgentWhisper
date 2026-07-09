"""X11 desktop backend: clipboard (xclip), typing (xdotool), window
listing (python-xlib/EWMH), and notifications (notify-send) — the
external tools are verified at startup by check()."""

from __future__ import annotations

import os
import shutil
import subprocess

from agentwhisper.desktop.base import DesktopError


def _best_icon(data: list[int], target: int = 48) -> tuple[int, int, list[int]] | None:
    """_NET_WM_ICON is a flat array of one or more (width, height,
    width*height ARGB pixels) blocks; pick the size closest to target."""
    icons = []
    i = 0
    while i + 2 <= len(data):
        width, height = data[i], data[i + 1]
        if width <= 0 or height <= 0 or i + 2 + width * height > len(data):
            break
        icons.append((width, height, list(data[i + 2:i + 2 + width * height])))
        i += 2 + width * height
    if not icons:
        return None
    return min(icons, key=lambda icon: abs(icon[0] - target))


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

    def select_window(self) -> tuple[str, str]:
        try:
            result = subprocess.run(
                ["xdotool", "selectwindow"],
                timeout=30,
                check=True,
                capture_output=True,
            )
        except FileNotFoundError as e:
            raise DesktopError("xdotool is not installed — sudo apt install xdotool") from e
        except subprocess.TimeoutExpired as e:
            raise DesktopError("no window was clicked within 30 seconds") from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode(errors="replace").strip()
            raise DesktopError(f"window selection failed: {stderr or e}") from e
        window_id = result.stdout.decode().strip()
        title = self.window_title(window_id) if window_id else None
        if title is None:
            raise DesktopError("could not identify the clicked window")
        return window_id, title

    def window_title(self, window_id: str) -> str | None:
        try:
            result = subprocess.run(
                ["xdotool", "getwindowname", window_id],
                timeout=5,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired):
            return None
        return result.stdout.decode(errors="replace").strip() or "(untitled)"

    def type_into_window(self, window_id: str, text: str) -> None:
        # Real (XTEST) keystrokes only reach the window that has input
        # focus — synthetic events to unfocused windows are ignored by
        # many apps, VTE terminals among them. So the target borrows the
        # keyboard for just the keystrokes: windowfocus moves focus
        # WITHOUT raising the window, and focus returns to the user's
        # window right after — dictating into a background agent window
        # never pulls it in front of what the user is doing.
        timeout = 10 + len(text) / 40
        original = self._active_window()
        restore = original if original and original != window_id else None
        try:
            subprocess.run(
                ["xdotool", "windowfocus", "--sync", window_id],
                timeout=5, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            try:
                subprocess.run(
                    ["xdotool", "type", "--clearmodifiers", "--", text],
                    timeout=timeout, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers", "Return"],
                    timeout=5, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
            finally:
                # Give focus back even if typing failed halfway;
                # best-effort — a vanished original window is fine.
                if restore is not None:
                    subprocess.run(
                        ["xdotool", "windowfocus", restore],
                        timeout=5, check=False,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
        except FileNotFoundError as e:
            raise DesktopError("xdotool is not installed — sudo apt install xdotool") from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode(errors="replace").strip()
            raise DesktopError(f"xdotool failed: {stderr or e}") from e
        except subprocess.TimeoutExpired as e:
            raise DesktopError("xdotool timed out while typing") from e

    def _active_window(self) -> str | None:
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow"],
                timeout=5, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired):
            return None
        return result.stdout.decode().strip() or None

    def list_windows(self) -> list[dict]:
        """Every normal application window, in the window manager's
        stacking order: [{"id", "title", "icon"}], icon being an
        (width, height, [argb, ...]) block from _NET_WM_ICON or None.
        AgentWhisper's own windows are left out."""
        if not os.environ.get("DISPLAY"):
            raise DesktopError("no DISPLAY: the window list needs a graphical X11 session")
        try:
            from Xlib import X
            from Xlib import display as xlib_display
        except ImportError as e:  # python-xlib is a hard dependency; be loud anyway
            raise DesktopError("python-xlib is not installed (pip install python-xlib)") from e
        try:
            disp = xlib_display.Display()
        except Exception as e:
            raise DesktopError(f"cannot connect to the X display: {e}") from e
        try:
            root = disp.screen().root
            client_list = root.get_full_property(
                disp.intern_atom("_NET_CLIENT_LIST"), X.AnyPropertyType)
            if client_list is None:
                raise DesktopError(
                    "the window manager does not publish a window list (_NET_CLIENT_LIST)")
            type_atom = disp.intern_atom("_NET_WM_WINDOW_TYPE")
            normal_atom = disp.intern_atom("_NET_WM_WINDOW_TYPE_NORMAL")
            name_atom = disp.intern_atom("_NET_WM_NAME")
            utf8_atom = disp.intern_atom("UTF8_STRING")
            icon_atom = disp.intern_atom("_NET_WM_ICON")
            windows = []
            for wid in client_list.value:
                try:
                    win = disp.create_resource_object("window", wid)
                    kinds = win.get_full_property(type_atom, X.AnyPropertyType)
                    if kinds is not None and normal_atom not in kinds.value:
                        continue  # panels, docks, notifications, ...
                    wm_class = win.get_wm_class() or ()
                    if any("agentwhisper" in c.lower() for c in wm_class):
                        continue
                    name = win.get_full_property(name_atom, utf8_atom)
                    if name is not None and name.value:
                        value = name.value
                        title = (value.decode("utf-8", "replace")
                                 if isinstance(value, bytes) else str(value))
                    else:
                        title = win.get_wm_name() or ""
                    if not title:
                        continue
                    icon_prop = win.get_full_property(icon_atom, X.AnyPropertyType)
                    icon = (_best_icon(list(icon_prop.value))
                            if icon_prop is not None else None)
                    windows.append({"id": str(wid), "title": title, "icon": icon})
                except Exception:
                    continue  # a window closed mid-scan; skip it
            return windows
        finally:
            disp.close()

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
