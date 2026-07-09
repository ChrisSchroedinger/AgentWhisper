"""XFCE panel tray icon via GTK/AyatanaAppIndicator (StatusNotifier).

Deliberately NOT pystray: soupawhisper died on pystray silently picking
a dead XEmbed backend. Here we bind the real thing directly — if the
bindings are missing, create_tray() raises TrayUnavailable with the
exact command that fixes it, and the caller decides what to do.

Requires the system GTK bindings, visible because install.sh creates
the venv with --system-site-packages:
    sudo apt install python3-gi python3-gi-cairo gir1.2-ayatanaappindicator3-0.1
"""

from __future__ import annotations

from importlib import resources

from agentwhisper import __version__

APT_HINT = "sudo apt install python3-gi python3-gi-cairo gir1.2-ayatanaappindicator3-0.1"

MODE_LABELS = {
    "hold": "Hold to talk (hold the key)",
    "toggle": "Press to toggle (press to start/stop)",
}

# Offered recording limits (seconds), spanning the allowed range
# (config.LIMIT_MIN..LIMIT_MAX). A hand-edited config value between
# presets still shows up in the menu as its own "(custom)" entry.
LIMIT_PRESETS = [30, 60, 120, 300, 600]


def _limit_label(seconds: int) -> str:
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute" + ("s" if minutes != 1 else "")
    return f"{seconds} seconds"


def _argb_to_rgba(pixels: list[int], width: int, height: int) -> bytes:
    """_NET_WM_ICON pixels are packed 32-bit ARGB; GdkPixbuf wants RGBA."""
    out = bytearray(width * height * 4)
    for i, pixel in enumerate(pixels):
        pixel &= 0xFFFFFFFF
        out[i * 4:i * 4 + 4] = ((pixel >> 16) & 0xFF, (pixel >> 8) & 0xFF,
                                pixel & 0xFF, (pixel >> 24) & 0xFF)
    return bytes(out)


class TrayUnavailable(Exception):
    """Tray cannot run; the message says why and how to fix it."""


def _import_gtk():
    try:
        import gi
    except ImportError as e:
        raise TrayUnavailable(
            "python3-gi (PyGObject) is not importable. If it is installed, the "
            "virtualenv was created without --system-site-packages (rerun install.sh); "
            f"if not: {APT_HINT}"
        ) from e
    try:
        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3, GLib, Gtk
    except (ImportError, ValueError) as e:
        raise TrayUnavailable(
            f"GTK/AyatanaAppIndicator bindings missing or wrong version: {e}. "
            f"Fix: {APT_HINT}"
        ) from e
    return Gtk, GLib, AyatanaAppIndicator3


def _icon_dir() -> str:
    """Directory holding the agentwhisper icons, shipped inside the package."""
    return str(resources.files("agentwhisper") / "icons")


class Tray:
    """Owns the GTK main loop. Constructed via create_tray()."""

    def __init__(self, app):
        """`app` provides: is_enabled(), set_enabled(bool), get_mode(),
        set_mode(str), get_max_record_seconds(), set_max_record_seconds(int),
        get_target_title(), list_target_windows(), set_target_window(id, title),
        clear_target_window(), hotkey_name(), quit()."""
        Gtk, GLib, AppIndicator = _import_gtk()
        self._gtk = Gtk
        self._glib = GLib
        self._appindicator = AppIndicator
        self._app = app
        self._updating_menu = False  # guard against signal feedback loops

        self.indicator = AppIndicator.Indicator.new_with_path(
            "agentwhisper",
            "agentwhisper",
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
            _icon_dir(),
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("AgentWhisper")
        self.indicator.set_menu(self._build_menu())
        self._refresh_status_label()

    def _build_menu(self):
        Gtk = self._gtk
        menu = Gtk.Menu()

        header = Gtk.MenuItem(label=f"AgentWhisper {__version__}")
        header.set_sensitive(False)
        menu.append(header)

        self._status_item = Gtk.MenuItem(label="")
        self._status_item.set_sensitive(False)
        menu.append(self._status_item)

        menu.append(Gtk.SeparatorMenuItem())

        self._enabled_item = Gtk.CheckMenuItem(label="Enabled")
        self._enabled_item.set_active(self._app.is_enabled())
        self._enabled_item.connect("toggled", self._on_enabled_toggled)
        menu.append(self._enabled_item)

        self._autotype_item = Gtk.CheckMenuItem(label="Auto-Type into active window")
        self._autotype_item.set_active(self._app.is_auto_type())
        self._autotype_item.connect("toggled", self._on_autotype_toggled)
        menu.append(self._autotype_item)

        self._notify_item = Gtk.CheckMenuItem(label="Notifications")
        self._notify_item.set_active(self._app.is_notifications())
        self._notify_item.connect("toggled", self._on_notify_toggled)
        menu.append(self._notify_item)

        self._autostart_item = Gtk.CheckMenuItem(label="Start at login")
        self._autostart_item.set_active(self._app.is_autostart())
        self._autostart_item.connect("toggled", self._on_autostart_toggled)
        menu.append(self._autostart_item)

        mode_item = Gtk.MenuItem(label="Recording Mode")
        mode_menu = Gtk.Menu()
        self._mode_items = {}
        group = None
        for mode, label in MODE_LABELS.items():
            item = Gtk.RadioMenuItem(label=label, group=group)
            group = item
            item.connect("toggled", self._on_mode_toggled, mode)
            self._mode_items[mode] = item
            mode_menu.append(item)
        self._updating_menu = True
        self._mode_items[self._app.get_mode()].set_active(True)
        self._updating_menu = False
        mode_item.set_submenu(mode_menu)
        menu.append(mode_item)

        limit_item = Gtk.MenuItem(label="Recording Limit")
        limit_menu = Gtk.Menu()
        self._limit_items = {}
        group = None
        current = self._app.get_max_record_seconds()
        offered = sorted(set(LIMIT_PRESETS) | {current})
        for seconds in offered:
            label = _limit_label(seconds)
            if seconds not in LIMIT_PRESETS:
                label += " (custom)"
            item = Gtk.RadioMenuItem(label=label, group=group)
            group = item
            item.connect("toggled", self._on_limit_toggled, seconds)
            self._limit_items[seconds] = item
            limit_menu.append(item)
        self._updating_menu = True
        self._limit_items[current].set_active(True)
        self._updating_menu = False
        limit_item.set_submenu(limit_menu)
        menu.append(limit_item)

        self._target_item = Gtk.MenuItem(label="")
        self._target_item.connect("activate", self._on_target_clicked)
        menu.append(self._target_item)
        self._refresh_target_label()

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit AgentWhisper")
        quit_item.connect("activate", lambda item: self._app.quit())
        menu.append(quit_item)

        menu.show_all()
        return menu

    # -- menu signal handlers ---------------------------------------------

    def _on_enabled_toggled(self, item):
        if not self._updating_menu:
            self._app.set_enabled(item.get_active())
            self._refresh_status_label()

    def _on_mode_toggled(self, item, mode):
        if not self._updating_menu and item.get_active():
            self._app.set_mode(mode)
            self._refresh_status_label()

    def _on_limit_toggled(self, item, seconds):
        if not self._updating_menu and item.get_active():
            self._app.set_max_record_seconds(seconds)

    def _on_target_clicked(self, item):
        if self._app.get_target_title() is not None:
            self._app.clear_target_window()
            return
        self._show_window_picker()

    def _show_window_picker(self):
        """A grid of the open windows; clicking one makes it the
        dictation target. Runs on the GTK thread (menu handler)."""
        Gtk = self._gtk
        windows = self._app.list_target_windows()
        if not windows:
            return  # the daemon already notified why
        picker = Gtk.Window(title="AgentWhisper — Choose active window")
        picker.set_keep_above(True)
        picker.set_position(Gtk.WindowPosition.CENTER)
        picker.set_border_width(12)
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(4)
        flow.set_min_children_per_line(min(4, len(windows)))
        flow.set_row_spacing(8)
        flow.set_column_spacing(8)
        for window in windows:
            button = Gtk.Button()
            button.set_relief(Gtk.ReliefStyle.NONE)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_border_width(6)
            box.pack_start(self._window_icon_image(window["icon"]), False, False, 0)
            title = window["title"]
            if len(title) > 28:
                title = title[:27] + "…"
            label = Gtk.Label(label=title)
            label.set_max_width_chars(28)
            label.set_line_wrap(True)
            box.pack_start(label, False, False, 0)
            button.add(box)
            button.connect("clicked", self._on_window_picked,
                           window["id"], window["title"], picker)
            flow.add(button)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_max_content_height(480)
        scroller.set_propagate_natural_height(True)
        scroller.add(flow)
        picker.add(scroller)
        picker.show_all()
        picker.present()

    def _on_window_picked(self, button, window_id, title, picker):
        picker.destroy()
        self._app.set_target_window(window_id, title)

    def _window_icon_image(self, icon):
        """A 48px Gtk.Image from a window's _NET_WM_ICON data, or a
        generic application icon when there is none."""
        Gtk = self._gtk
        if icon:
            try:
                from gi.repository import GdkPixbuf
                width, height, pixels = icon
                pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
                    self._glib.Bytes.new(_argb_to_rgba(pixels, width, height)),
                    GdkPixbuf.Colorspace.RGB, True, 8, width, height, width * 4)
                if width != 48 or height != 48:
                    pixbuf = pixbuf.scale_simple(
                        48, 48, GdkPixbuf.InterpType.BILINEAR)
                return Gtk.Image.new_from_pixbuf(pixbuf)
            except Exception:
                pass  # malformed icon data — fall back to the generic one
        image = Gtk.Image.new_from_icon_name(
            "application-x-executable", Gtk.IconSize.DIALOG)
        image.set_pixel_size(48)
        return image

    def _on_autotype_toggled(self, item):
        if not self._updating_menu:
            self._app.set_auto_type(item.get_active())

    def _on_notify_toggled(self, item):
        if not self._updating_menu:
            self._app.set_notifications(item.get_active())

    def _on_autostart_toggled(self, item):
        if not self._updating_menu:
            self._app.set_autostart(item.get_active())

    # -- state display (thread-safe) ----------------------------------------

    def set_state(self, state: str) -> None:
        """'idle' | 'recording' | 'transcribing' — safe from any thread."""
        self._glib.idle_add(self._set_state_on_gtk_thread, state)

    def refresh_target(self) -> None:
        """Re-render the target-window menu item — safe from any thread."""
        self._glib.idle_add(self._refresh_target_label)

    def _refresh_target_label(self) -> bool:
        title = self._app.get_target_title()
        if title is None:
            self._target_item.set_label("Choose active window…")
        else:
            if len(title) > 32:
                title = title[:31] + "…"
            self._target_item.set_label(f"Stop dictating into: {title}")
        return False

    def _set_state_on_gtk_thread(self, state: str) -> bool:
        if state == "recording":
            self.indicator.set_icon_full("agentwhisper-recording", "recording")
            self._status_item.set_label("● Recording…")
        elif state == "transcribing":
            self.indicator.set_icon_full("agentwhisper", "transcribing")
            self._status_item.set_label("⋯ Transcribing…")
        else:
            self.indicator.set_icon_full("agentwhisper", "idle")
            self._refresh_status_label()
        return False

    def _refresh_status_label(self) -> None:
        key = self._app.hotkey_name().upper()
        engine = self._app.engine_status()
        if engine.startswith("downloading"):
            percent = engine.removeprefix("downloading").strip()
            text = f"Downloading speech model… {percent or '0%'} (one time)"
        elif engine in ("loading", "not loaded"):
            text = "Preparing speech model…"
        elif engine.startswith("error"):
            text = "Speech model failed — see agentwhisper status"
        elif not self._app.is_enabled():
            text = "Disabled"
        elif self._app.get_mode() == "hold":
            text = f"Ready — hold {key} to dictate"
        else:
            text = f"Ready — press {key} to start/stop"
        self._status_item.set_label(text)

    # -- lifecycle -----------------------------------------------------------

    def run(self):
        """Blocks in the GTK main loop; call from the main thread."""
        import signal

        # Gtk.main() blocks Python-level signal delivery; register with GLib.
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._glib.unix_signal_add(
                self._glib.PRIORITY_DEFAULT, sig, self._on_signal, None
            )
        self._gtk.main()

    def _on_signal(self, _data):
        self._app.quit()
        return self._glib.SOURCE_REMOVE

    def stop(self):
        """Thread-safe: unregisters the icon and ends the GTK main loop."""
        self._glib.idle_add(self._stop_on_gtk_thread)

    def _stop_on_gtk_thread(self) -> bool:
        import contextlib

        # Hide the indicator explicitly so the panel icon disappears the
        # instant the user quits, even if the process needs a moment to die.
        with contextlib.suppress(Exception):
            self.indicator.set_status(
                self._appindicator.IndicatorStatus.PASSIVE)
        self._gtk.main_quit()
        return False


def create_tray(app) -> Tray:
    """Raise TrayUnavailable (with remediation) if the panel tray can't work."""
    import os

    if not os.environ.get("DISPLAY"):
        raise TrayUnavailable("no DISPLAY: not a graphical session")
    return Tray(app)
