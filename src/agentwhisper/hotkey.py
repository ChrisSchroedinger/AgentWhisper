"""Exclusive global hotkey via X11 XGrabKey.

XGrabKey reserves the plain key system-wide: while agentwhisperd runs,
F12 (or whatever is configured) is delivered ONLY to us — it cannot
reach the focused application, so it never collides with in-app F12
hotkeys. Modifier combinations (Ctrl+F12, Alt+F12, ...) are untouched
and keep working for whoever owns them. If another client already holds
a grab on exactly the plain key, X answers BadAccess and we raise
HotkeyError telling the user how to find it or pick a different key.

Auto-repeat note: a held, grabbed key still produces synthetic
release/press pairs; the DictationStateMachine's debounce handles them.
"""

from __future__ import annotations

import os
import select
import threading

# Config names that don't resolve via simple capitalization.
_SPECIAL_KEYSYMS = {
    "scroll_lock": "Scroll_Lock",
    "pause": "Pause",
    "print": "Print",
    "menu": "Menu",
    "insert": "Insert",
}


class HotkeyError(Exception):
    """Hotkey cannot work; the message says why and what to do."""


def _resolve_keysym(name: str):
    from Xlib import XK

    for candidate in (_SPECIAL_KEYSYMS.get(name.lower()), name, name.upper(),
                      name.capitalize()):
        if candidate:
            keysym = XK.string_to_keysym(candidate)
            if keysym != 0:
                return keysym
    raise HotkeyError(
        f"unknown hotkey {name!r} — try f1..f12, scroll_lock, pause, insert, menu"
    )


class X11HotkeyListener:
    """Grabs the key and reports raw press/release events from a thread."""

    def __init__(self, key_name: str, on_press, on_release):
        self.key_name = key_name
        self._on_press = on_press
        self._on_release = on_release
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._display = None
        self._keycode = None

    def start(self) -> None:
        """Grab the key or raise HotkeyError. Returns once the grab holds."""
        if not os.environ.get("DISPLAY"):
            raise HotkeyError("no DISPLAY: hotkey capture needs a graphical X11 session")

        from Xlib import X
        from Xlib import display as xdisplay
        from Xlib.error import BadAccess, CatchError

        self._display = xdisplay.Display()
        root = self._display.screen().root
        keysym = _resolve_keysym(self.key_name)
        self._keycode = self._display.keysym_to_keycode(keysym)
        if self._keycode == 0:
            raise HotkeyError(f"key {self.key_name!r} has no keycode on this keyboard layout")

        # Grab ONLY the plain key (plus CapsLock/NumLock variants so it
        # still fires while those locks are on). NOT AnyModifier: X11
        # treats that as "every modifier combination", which collides
        # with unrelated bindings like Ctrl+F12 or Alt+F12 held by the
        # desktop environment and fails the whole grab with BadAccess.
        catch = CatchError(BadAccess)
        for mask in self._lock_variant_masks():
            root.grab_key(self._keycode, mask, False,
                          X.GrabModeAsync, X.GrabModeAsync, onerror=catch)
        self._display.sync()
        if catch.get_error():
            root.ungrab_key(self._keycode, X.AnyModifier)  # drop any partial grabs
            self._display.close()
            self._display = None
            raise HotkeyError(
                f"could not reserve {self.key_name!r}: another application already "
                f"grabbed exactly this key. Find it by pressing the key and seeing "
                f"what reacts, or choose a different key in "
                f"~/.config/agentwhisper/config.toml ([hotkey] key = ...)"
            )

        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()

    def _lock_variant_masks(self) -> set[int]:
        """Modifier masks to grab: none, CapsLock, NumLock, and both.

        NumLock's mask is not fixed in X11; find which modifier slot the
        Num_Lock keysym is mapped to (commonly Mod2).
        """
        from Xlib import XK, X

        numlock_mask = 0
        numlock_keycode = self._display.keysym_to_keycode(
            XK.string_to_keysym("Num_Lock"))
        if numlock_keycode:
            for mod_index, keycodes in enumerate(self._display.get_modifier_mapping()):
                if numlock_keycode in keycodes:
                    numlock_mask = 1 << mod_index
        return {0, X.LockMask, numlock_mask, X.LockMask | numlock_mask}

    def _run(self) -> None:
        from Xlib import X

        display = self._display
        fd = display.fileno()
        try:
            while not self._stop.is_set():
                readable, _, _ = select.select([fd], [], [], 0.25)
                if not readable:
                    continue
                while display.pending_events():
                    event = display.next_event()
                    if getattr(event, "detail", None) != self._keycode:
                        continue
                    if event.type == X.KeyPress:
                        self._on_press()
                    elif event.type == X.KeyRelease:
                        self._on_release()
        finally:
            try:
                display.screen().root.ungrab_key(self._keycode, X.AnyModifier)
                display.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
