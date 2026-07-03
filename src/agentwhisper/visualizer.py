"""Recording OSD: a semi-transparent popup near the bottom of the screen
with green equalizer bars that follow the microphone level.

Runs on the GTK main loop the daemon already owns for the tray; show()
and hide() are thread-safe. Needs the same GTK bindings as the tray
plus cairo support (python3-gi-cairo); if those are missing the daemon
simply runs without the OSD.

Look: rounded dark pill, ~15% above the bottom edge, horizontally
centered on the primary monitor. Bar heights show the last ~1.2s of
mic level scrolling right-to-left, newest on the right.
"""

from __future__ import annotations

from collections import deque

WIDTH = 380
HEIGHT = 84
BOTTOM_MARGIN_FRACTION = 0.15  # of monitor height, above the bottom edge
BARS = 28
FRAME_MS = 70                  # one new bar per frame — this sets the slide speed
SENSITIVITY = 14.0             # raw speech RMS is ~0.02–0.2; boost for display


class VisualizerUnavailable(Exception):
    pass


class Visualizer:
    def __init__(self, level_source):
        """`level_source` is a zero-arg callable returning RMS 0.0–1.0."""
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            from gi.repository import Gdk, GLib, Gtk
        except (ImportError, ValueError) as e:
            raise VisualizerUnavailable(
                f"GTK bindings missing: {e}. "
                f"Fix: sudo apt install python3-gi python3-gi-cairo"
            ) from e

        self._gtk, self._gdk, self._glib = Gtk, Gdk, GLib
        self._level_source = level_source
        self._levels = deque([0.0] * BARS, maxlen=BARS)
        self._timer_id = None

        self._window = Gtk.Window(type=Gtk.WindowType.POPUP)
        self._window.set_default_size(WIDTH, HEIGHT)
        self._window.set_decorated(False)
        self._window.set_accept_focus(False)
        self._window.set_keep_above(True)
        self._window.set_app_paintable(True)

        screen = self._window.get_screen()
        visual = screen.get_rgba_visual()
        self._composited = visual is not None and screen.is_composited()
        if visual is not None:
            self._window.set_visual(visual)

        area = Gtk.DrawingArea()
        area.connect("draw", self._on_draw)
        self._window.add(area)

    # -- thread-safe API -------------------------------------------------

    def show(self) -> None:
        self._glib.idle_add(self._show_on_gtk_thread)

    def hide(self) -> None:
        self._glib.idle_add(self._hide_on_gtk_thread)

    # -- GTK-thread internals ---------------------------------------------

    def _show_on_gtk_thread(self) -> bool:
        self._levels.extend([0.0] * BARS)
        self._place()
        self._window.show_all()
        if self._timer_id is None:
            self._timer_id = self._glib.timeout_add(FRAME_MS, self._on_frame)
        return False  # do not repeat this idle callback

    def _hide_on_gtk_thread(self) -> bool:
        if self._timer_id is not None:
            self._glib.source_remove(self._timer_id)
            self._timer_id = None
        self._window.hide()
        return False

    def _place(self) -> None:
        display = self._gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        area = monitor.get_workarea()
        x = area.x + (area.width - WIDTH) // 2
        y = area.y + area.height - HEIGHT - int(area.height * BOTTOM_MARGIN_FRACTION)
        self._window.move(x, y)

    def _on_frame(self) -> bool:
        raw = float(self._level_source())
        self._levels.append(min(1.0, raw * SENSITIVITY))
        self._window.queue_draw()
        return True  # keep the timer running

    def _on_draw(self, _widget, cr) -> bool:
        # Background: rounded dark pill, semi-transparent when composited.
        alpha = 0.55 if self._composited else 1.0
        self._rounded_rect(cr, 0, 0, WIDTH, HEIGHT, 16)
        cr.set_source_rgba(0.07, 0.09, 0.11, alpha)
        cr.fill()

        # Bars: green, symmetric around the vertical center.
        slot = WIDTH / BARS
        bar_width = slot * 0.55
        max_bar = HEIGHT - 24
        center_y = HEIGHT / 2
        for i, level in enumerate(self._levels):
            height = max(4.0, (level**0.7) * max_bar)
            x = i * slot + (slot - bar_width) / 2
            # Brighter green the louder it is.
            cr.set_source_rgba(0.18 + 0.16 * level, 0.80 + 0.12 * level, 0.44, 0.95)
            self._rounded_rect(cr, x, center_y - height / 2, bar_width, height,
                               bar_width / 2)
            cr.fill()
        return False

    @staticmethod
    def _rounded_rect(cr, x, y, w, h, r):
        import math

        r = min(r, w / 2, h / 2)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
