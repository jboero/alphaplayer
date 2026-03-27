#!/usr/bin/env python3
"""
AlphaPlayer
============
Plays VP9 WebM videos with alpha transparency as a desktop overlay on Wayland.

Copyright (C) 2025 John Boero and Claude (Anthropic)
Vibe coded with love.

License: LGPLv3 — see https://www.gnu.org/licenses/lgpl-3.0.html

Requirements:
    - Python 3.10+
    - PyGObject (gi) with GTK 4.0, Gdk 4.0, GLib 2.0, Gst 1.0, GstVideo 1.0
    - GStreamer plugins: gst-plugins-good (VP9), gst-plugins-base (videoconvert)
    - Optional: gtk4-layer-shell (for keep-above/below on Wayland)

Usage:
    ./overlay_player.py <video.webm>
    ./overlay_player.py --position 100,200 --size 320x240 video.webm
    ./overlay_player.py --position -50,-50 video.webm   # 50px from bottom-right
    ./overlay_player.py --hide-controls --no-loop video.webm
    ./overlay_player.py --exit intro.webm lesson.webm    # play then quit
    ./overlay_player.py https://example.com/overlay.webm # stream from URL
    ./overlay_player.py --hide-controls ./*.webm         # playlist of all webm files
    ./overlay_player.py --help

Controls:
    Space              Toggle pause
    Double-click       Maximize / restore
    Drag anywhere      Move window
    Right-click        Context menu
    N / Right arrow    Next in playlist
    P / Left arrow     Previous in playlist
    F                  Toggle frameless mode
    T                  Toggle always-on-top
    O / Scroll Up      Increase opacity
    Shift+O / Scroll Dn  Decrease opacity
    L                  Toggle loop
    R                  Restart video
    Ctrl+Q / Alt+F4    Quit
    Escape             Quit
"""

APP_ID = "io.github.alphaplayer"
APP_NAME = "AlphaPlayer"
APP_VERSION = "1.2"

import argparse
import os
import signal
import subprocess
import sys
import tempfile

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gst, GstVideo, Gtk

# ── Optional: gtk4-layer-shell for Wayland stacking ─────────────────────────
# This is the only reliable way to do keep-above/keep-below on Wayland.
# Without it, stacking changes only work on X11/XWayland.

HAS_LAYER_SHELL = False
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell
    HAS_LAYER_SHELL = True
except (ValueError, ImportError):
    pass


# ── Suppress known-harmless GTK warnings ─────────────────────────────────────
# GTK4's CSS engine emits warnings for properties it doesn't recognise
# (e.g. "text-align" from some themes) and for internal layout glitches
# (e.g. the GtkGizmo "min height -2" bug).  These are not our fault and
# cannot be fixed from application code, so we filter them out.

_GTK_WARN_FILTERS = (
    "Theme parser error",
    "No property named",
    "reported min height",
    "reported min width",
)


def _gtk_log_filter(*args):
    """Suppress noisy GTK warnings that we can't fix.
    Signature varies by PyGObject version — accept *args to be safe."""
    # args is typically (log_domain, log_level, fields) or
    # (log_domain, log_level, message, user_data)
    # The fields variant passes a GLib.LogField array; we need to
    # extract the MESSAGE field from it.
    msg = ""
    domain = args[0] if len(args) > 0 else ""
    if len(args) >= 3:
        fields = args[2]
        if isinstance(fields, str):
            msg = fields
        elif hasattr(fields, '__iter__'):
            # fields is a sequence of GLib.LogField structs
            for f in fields:
                try:
                    if hasattr(f, 'key') and f.key == "MESSAGE":
                        msg = f.value if hasattr(f, 'value') else str(f)
                        break
                except Exception:
                    pass
            if not msg:
                msg = str(fields)

    if domain and str(domain).startswith("Gtk"):
        for filt in _GTK_WARN_FILTERS:
            if filt in str(msg):
                return GLib.LogWriterOutput.HANDLED
    return GLib.LogWriterOutput.UNHANDLED


# Install the filter before any GTK calls
GLib.log_set_writer_func(_gtk_log_filter)


# ── Utility ──────────────────────────────────────────────────────────────────

def media_uri(path: str) -> str:
    """Return a GStreamer-compatible URI for a local path or remote URL."""
    if path.startswith(("http://", "https://", "file://")):
        return path
    return "file://" + os.path.abspath(path)


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def icon_path() -> str:
    return os.path.join(script_dir(), "alphaplayer_icon.webp")


def is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


# ── Icon Registration ────────────────────────────────────────────────────────

ICON_NAME = "alphaplayer"


def register_icon():
    """
    Convert alphaplayer_icon.webp → PNG in a temp hicolor tree so GTK4's
    icon theme can resolve it by name (GTK4 dropped per-window pixbuf icons).
    """
    src = icon_path()
    if not os.path.isfile(src):
        return
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(src)
        icon_dir = os.path.join(tempfile.gettempdir(), "alphaplayer-icons",
                                "hicolor", "256x256", "apps")
        os.makedirs(icon_dir, exist_ok=True)
        dest = os.path.join(icon_dir, f"{ICON_NAME}.png")
        pb.savev(dest, "png", [], [])
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        theme.add_search_path(
            os.path.join(tempfile.gettempdir(), "alphaplayer-icons"))
    except Exception as e:
        print(f"Icon registration: {e}", file=sys.stderr)


# ── Screen geometry helper ───────────────────────────────────────────────────

def get_screen_size() -> tuple[int, int]:
    """Return (width, height) of the default monitor."""
    display = Gdk.Display.get_default()
    if display is None:
        return (1920, 1080)
    monitors = display.get_monitors()
    if monitors.get_n_items() == 0:
        return (1920, 1080)
    mon = monitors.get_item(0)
    geo = mon.get_geometry()
    return (geo.width, geo.height)


def resolve_position(pos_x: int, pos_y: int,
                     win_w: int, win_h: int) -> tuple[int, int]:
    """
    Resolve window position.  Negative values mean offset from the
    right/bottom edge of the screen.
      -1   → 1px from right/bottom edge
      -50  → 50px from right/bottom edge
    """
    scr_w, scr_h = get_screen_size()
    x = pos_x if pos_x >= 0 else scr_w + pos_x - win_w
    y = pos_y if pos_y >= 0 else scr_h + pos_y - win_h
    return (max(0, x), max(0, y))


# ── GStreamer Pipeline ───────────────────────────────────────────────────────

class VideoPipeline:
    """Decodes VP9+alpha WebM → RGBA frames → GTK4 paintable."""

    def __init__(self, uri: str, on_eos=None):
        Gst.init(None)
        self.uri = uri
        self._on_eos = on_eos
        self._volume = 1.0
        self._pre_mute_vol = 1.0

        self.pipeline = Gst.ElementFactory.make("playbin3", "playbin")
        if self.pipeline is None:
            self.pipeline = Gst.ElementFactory.make("playbin", "playbin")
        if self.pipeline is None:
            raise RuntimeError("Could not create playbin element.")

        self.pipeline.set_property("uri", uri)

        # Probe for a GTK4-native video sink
        self._sink_name = None
        for name in ("gtk4paintablesink", "gtk4sink"):
            self.gtksink = Gst.ElementFactory.make(name, "vsink")
            if self.gtksink is not None:
                self._sink_name = name
                break
        if self.gtksink is None:
            raise RuntimeError(
                "No GTK4 video sink found.\n"
                "  Fedora:  sudo dnf install gstreamer1-plugin-gtk4\n"
                "  Ubuntu:  sudo apt install gstreamer1.0-gtk4")

        videoconvert = Gst.ElementFactory.make("videoconvert", "vconv")
        sink_bin = Gst.Bin.new("sink_bin")
        sink_bin.add(videoconvert)
        sink_bin.add(self.gtksink)
        videoconvert.link(self.gtksink)
        ghost = Gst.GhostPad.new("sink", videoconvert.get_static_pad("sink"))
        sink_bin.add_pad(ghost)
        self.pipeline.set_property("video-sink", sink_bin)
        self.pipeline.set_property("volume", self._volume)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", self._on_bus_eos)
        bus.connect("message::error", self._on_bus_error)

    @property
    def paintable(self):
        if self._sink_name in ("gtk4paintablesink", "gtk4sink"):
            return self.gtksink.get_property("paintable")
        raise RuntimeError(f"Sink '{self._sink_name}' has no paintable.")

    def play(self):
        self.pipeline.set_state(Gst.State.PLAYING)

    def pause(self):
        self.pipeline.set_state(Gst.State.PAUSED)

    def toggle_pause(self):
        _, state, _ = self.pipeline.get_state(Gst.CLOCK_TIME_NONE // 1000)
        (self.pause if state == Gst.State.PLAYING else self.play)()

    def restart(self):
        self.pipeline.seek_simple(
            Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)
        self.play()

    def change_uri(self, uri: str):
        """Switch to a different file.  Stops, changes URI, and plays."""
        self.pipeline.set_state(Gst.State.NULL)
        self.uri = uri
        self.pipeline.set_property("uri", uri)
        self.pipeline.set_state(Gst.State.PLAYING)

    def shutdown(self):
        self.pipeline.set_state(Gst.State.NULL)

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, val: float):
        self._volume = max(0.0, min(1.5, val))
        self.pipeline.set_property("volume", self._volume)

    def toggle_mute(self):
        if self._volume > 0:
            self._pre_mute_vol = self._volume
            self.volume = 0.0
        else:
            self.volume = self._pre_mute_vol if self._pre_mute_vol > 0 else 1.0

    def _on_bus_eos(self, _bus, _msg):
        if self._on_eos:
            GLib.idle_add(self._on_eos)

    @staticmethod
    def _on_bus_error(_bus, msg):
        err, debug = msg.parse_error()
        print(f"GStreamer error: {err.message}", file=sys.stderr)
        if debug:
            print(f"  debug: {debug}", file=sys.stderr)


# ── Overlay Window ───────────────────────────────────────────────────────────

class OverlayWindow(Gtk.ApplicationWindow):
    """Transparent video overlay with auto-hiding controls and context menu."""

    OPACITY_STEP = 0.05
    AUTOHIDE_MS = 5000

    def __init__(self, app, playlist: list[str], *,
                 loop: bool = True,
                 exit_after: bool = False,
                 controls_mode: str = "autohide",
                 position: tuple[int, int] | None = None,
                 size: tuple[int, int] | str = (480, 480)):
        super().__init__(application=app, title=APP_NAME)
        self._playlist = playlist
        self._playlist_idx = 0
        self._loop = loop
        self._exit_after = exit_after
        self._frameless = True
        self._on_top = False
        self._opacity = 1.0
        self._controls_mode = controls_mode  # "autohide" | "hidden" | "shown"
        self._controls_visible = (controls_mode != "hidden")
        self._autohide_id = 0
        self._stacking = "normal"  # "normal" | "above" | "below"
        self._req_position = position
        self._start_maximized = (size == "max")
        self._req_size = (480, 480) if self._start_maximized else size

        self.set_icon_name(ICON_NAME)

        # ── Transparency CSS ────────────────────────────────────────────
        self.add_css_class("tvp")
        css = Gtk.CssProvider()
        css.load_from_string(
            "window.tvp, window.tvp > * {"
            "  background-color: transparent;"
            "  background: transparent;"
            "}"
            ".control-bar {"
            "  background: rgba(0,0,0,0.55);"
            "  border-radius: 8px;"
            "  padding: 4px 12px;"
            "}"
            ".control-bar button {"
            "  background: transparent; border: none; color: white;"
            "  min-width: 32px; min-height: 28px;"
            "  font-size: 13px; padding: 2px 8px;"
            "}"
            ".control-bar button:hover {"
            "  background: rgba(255,255,255,0.15); border-radius: 4px;"
            "}"
            ".control-bar .status-label {"
            "  color: rgba(255,255,255,0.7); font-size: 11px; padding: 0 4px;"
            "}"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # ── GStreamer ───────────────────────────────────────────────────
        self.pipeline = VideoPipeline(
            media_uri(self._current_file()), on_eos=self._handle_eos)

        # ── Widget tree ─────────────────────────────────────────────────
        self.picture = Gtk.Picture.new_for_paintable(self.pipeline.paintable)
        self.picture.set_can_shrink(True)
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)

        overlay = Gtk.Overlay()
        overlay.set_child(self.picture)
        self._build_controls(overlay)
        self.set_child(overlay)
        self.set_default_size(*self._req_size)
        self.set_decorated(False)  # frameless by default

        if self._start_maximized:
            self.maximize()

        # ── Window positioning ──────────────────────────────────────────
        # Must be set up BEFORE the window is mapped/realized.
        # On Wayland: use layer-shell margins (only way to position).
        # On X11: defer to a post-map callback with xdotool.
        self._layer_shell_active = False
        if position is not None and HAS_LAYER_SHELL and is_wayland():
            x, y = resolve_position(
                position[0], position[1],
                self._req_size[0], self._req_size[1])
            try:
                Gtk4LayerShell.init_for_window(self)
                Gtk4LayerShell.set_keyboard_mode(
                    self, Gtk4LayerShell.KeyboardMode.ON_DEMAND)
                Gtk4LayerShell.set_layer(
                    self, Gtk4LayerShell.Layer.TOP)
                Gtk4LayerShell.set_anchor(
                    self, Gtk4LayerShell.Edge.TOP, True)
                Gtk4LayerShell.set_anchor(
                    self, Gtk4LayerShell.Edge.LEFT, True)
                Gtk4LayerShell.set_margin(
                    self, Gtk4LayerShell.Edge.TOP, y)
                Gtk4LayerShell.set_margin(
                    self, Gtk4LayerShell.Edge.LEFT, x)
                self._layer_shell_active = True
                print(f"Position via layer-shell: {x},{y}", file=sys.stderr)
            except Exception as e:
                print(f"layer-shell position failed: {e}", file=sys.stderr)

        # Apply initial controls visibility
        if controls_mode == "hidden":
            self._bar.set_visible(False)

        # ── Input controllers ───────────────────────────────────────────
        key = Gtk.EventControllerKey.new()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        dbl = Gtk.GestureClick.new()
        dbl.set_button(1)
        dbl.connect("released", self._on_dblclick)
        self.picture.add_controller(dbl)

        drag = Gtk.GestureDrag.new()
        drag.set_button(1)
        drag.connect("drag-begin", self._on_drag_begin)
        self.picture.add_controller(drag)

        rclick = Gtk.GestureClick.new()
        rclick.set_button(3)
        rclick.connect("released", self._on_right_click)
        self.add_controller(rclick)

        # Focus / pointer tracking for auto-hide
        fc = Gtk.EventControllerFocus.new()
        fc.connect("enter", lambda _: self._show_controls())
        fc.connect("leave", lambda _: self._schedule_autohide())
        self.add_controller(fc)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("enter", lambda _c, _x, _y: self._show_controls())
        motion.connect("leave", lambda _c: self._schedule_autohide())
        self.add_controller(motion)

        self.connect("realize", self._on_realize)

    # ── Controls bar ────────────────────────────────────────────────────

    def _build_controls(self, overlay):
        self._bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._bar.set_halign(Gtk.Align.CENTER)
        self._bar.set_valign(Gtk.Align.END)
        self._bar.set_margin_bottom(10)
        self._bar.add_css_class("control-bar")

        def btn(label, tooltip, cb):
            b = Gtk.Button(label=label)
            b.set_tooltip_text(tooltip)
            b.connect("clicked", cb)
            self._bar.append(b)
            return b

        btn("⏯", "Play / Pause", lambda _: self.pipeline.toggle_pause())
        btn("↺", "Restart", lambda _: self.pipeline.restart())
        self._loop_btn = btn(
            "🔁" if self._loop else "🔂", "Loop",
            lambda _: self._toggle_loop())
        btn("▣", "Frame", lambda _: self._toggle_frameless())
        btn("📌", "On top", lambda _: self._toggle_on_top())
        btn("➕", "Opacity +",
            lambda _: self._adjust_opacity(self.OPACITY_STEP))
        btn("➖", "Opacity −",
            lambda _: self._adjust_opacity(-self.OPACITY_STEP))

        self._status = Gtk.Label(label="")
        self._status.add_css_class("status-label")
        self._bar.append(self._status)

        overlay.add_overlay(self._bar)

    # ── Controls auto-hide ──────────────────────────────────────────────
    # Three modes:
    #   "autohide" — show on pointer enter, hide 5s after leave
    #   "hidden"   — permanently hidden until "Show Controls"
    #   "shown"    — permanently visible until "Hide Controls"

    def _show_controls(self):
        if self._controls_mode == "hidden":
            return
        if not self._controls_visible:
            self._controls_visible = True
            self._bar.set_visible(True)
        if self._controls_mode == "autohide":
            self._cancel_autohide()

    def _hide_controls(self):
        if self._controls_mode != "autohide":
            return
        if self._controls_visible:
            self._controls_visible = False
            self._bar.set_visible(False)

    def _schedule_autohide(self):
        self._cancel_autohide()
        if self._controls_mode == "autohide":
            self._autohide_id = GLib.timeout_add(
                self.AUTOHIDE_MS, self._autohide_tick)

    def _cancel_autohide(self):
        if self._autohide_id:
            GLib.source_remove(self._autohide_id)
            self._autohide_id = 0

    def _autohide_tick(self):
        self._autohide_id = 0
        self._hide_controls()
        return False

    def _set_controls_mode(self, mode: str):
        self._controls_mode = mode
        self._cancel_autohide()
        if mode == "hidden":
            self._controls_visible = False
            self._bar.set_visible(False)
            self._flash("Controls hidden")
        elif mode == "shown":
            self._controls_visible = True
            self._bar.set_visible(True)
            self._flash("Controls shown")
        else:  # autohide
            self._controls_visible = True
            self._bar.set_visible(True)
            self._flash("Controls auto-hide")
            self._schedule_autohide()

    # ── Context menu (hand-built popover — no Gio.Menu) ─────────────────

    def _on_right_click(self, gesture, _n, x, y):
        if hasattr(self, "_popover") and self._popover is not None:
            self._popover.unparent()
            self._popover = None

        popover = Gtk.Popover()
        popover.set_parent(self)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.set_has_arrow(False)
        popover.set_autohide(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.add_css_class("ctx-menu")

        css = Gtk.CssProvider()
        css.load_from_string(
            ".ctx-menu { padding: 6px 0; }"
            ".ctx-menu button {"
            "  background: transparent; border: none; border-radius: 0;"
            "  padding: 6px 16px; min-height: 24px;"
            "}"
            ".ctx-menu button:hover {"
            "  background: alpha(currentColor, 0.08);"
            "}"
            ".ctx-sep {"
            "  min-height: 1px; margin: 4px 8px;"
            "  background: alpha(currentColor, 0.15);"
            "}"
            ".ctx-header {"
            "  padding: 4px 16px 2px 16px; font-size: 11px; opacity: 0.55;"
            "}"
            ".ctx-check { font-weight: bold; margin-right: 4px; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        def menu_btn(label, callback):
            b = Gtk.Button()
            lbl = Gtk.Label(label=label, xalign=0)
            b.set_child(lbl)
            b.connect("clicked", lambda _: (callback(), popover.popdown()))
            box.append(b)

        def separator():
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.add_css_class("ctx-sep")
            box.append(sep)

        def header(text):
            lbl = Gtk.Label(label=text, xalign=0)
            lbl.add_css_class("ctx-header")
            box.append(lbl)

        def check_btn(label, active: bool, callback):
            """Menu button with a checkmark indicator."""
            prefix = "  ✓  " if active else "      "
            menu_btn(f"{prefix}{label}", callback)

        # ── Menu items ──────────────────────────────────────────────
        if self._controls_mode == "hidden":
            menu_btn("Show Controls", lambda: self._set_controls_mode("autohide"))
        else:
            menu_btn("Hide Controls", lambda: self._set_controls_mode("hidden"))

        frame_label = "Show Frame" if self._frameless else "Hide Frame"
        menu_btn(frame_label, self._toggle_frameless)

        separator()

        # Stacking — radio-style with checks
        check_btn("Keep Above Others",
                   self._stacking == "above",
                   lambda: self._set_stacking("above"))
        check_btn("Keep Below Others",
                   self._stacking == "below",
                   lambda: self._set_stacking("below"))
        check_btn("Normal Stacking",
                   self._stacking == "normal",
                   lambda: self._set_stacking("normal"))

        separator()

        # Playlist (only show if multiple files)
        if len(self._playlist) > 1:
            name = os.path.basename(self._current_file())
            pos = f"{self._playlist_idx + 1}/{len(self._playlist)}"
            header(f"Playlist: {pos}  —  {name}")
            menu_btn("Next  [N / →]", self._playlist_next)
            menu_btn("Previous  [P / ←]", self._playlist_prev)
            separator()

        # Volume
        header(f"Volume: {self.pipeline.volume:.0%}")
        menu_btn("Volume Up (+10%)", lambda: self._adj_vol(0.1))
        menu_btn("Volume Down (−10%)", lambda: self._adj_vol(-0.1))
        mute_label = "Unmute" if self.pipeline.volume == 0 else "Mute"
        menu_btn(mute_label, self._do_mute)

        separator()

        menu_btn("About…", self._show_about)
        menu_btn("Quit", self.close)

        popover.set_child(box)
        popover.popup()
        self._popover = popover

    # ── Stacking ────────────────────────────────────────────────────────
    # Strategy cascade:
    #   1. gtk4-layer-shell (Wayland-native, if installed)
    #   2. wmctrl (X11/XWayland, if installed)
    #   3. xdotool + xprop (X11 fallback)
    # On Wayland without layer-shell there is simply no client API
    # for above/below — we tell the user.

    def _set_stacking(self, mode: str):
        self._stacking = mode

        if self._try_layer_shell_stacking(mode):
            return
        if self._try_wmctrl_stacking(mode):
            return
        if self._try_xdotool_stacking(mode):
            return

        if is_wayland():
            self._flash("Install gtk4-layer-shell for stacking")
            print(
                "Stacking requires gtk4-layer-shell on Wayland:\n"
                "  Fedora: sudo dnf install gtk4-layer-shell\n"
                "  Ubuntu: sudo apt install libgtk4-layer-shell-dev\n"
                "  Arch:   sudo pacman -S gtk4-layer-shell\n"
                "Or use the window titlebar menu (right-click taskbar icon).",
                file=sys.stderr)
        else:
            self._flash("Stacking not available")

    def _try_layer_shell_stacking(self, mode: str) -> bool:
        """
        Use gtk4-layer-shell to set the window layer.
          TOP      → above normal windows (≈ keep-above)
          BOTTOM   → below normal windows (≈ keep-below)
          OVERLAY  → above everything including panels

        If layer-shell was already initialized (e.g. for positioning),
        we just switch layers.  If not, we can only init it before the
        window is mapped — so if it's already showing, this won't work.
        """
        if not HAS_LAYER_SHELL:
            return False

        try:
            is_layer = Gtk4LayerShell.is_layer_window(self)

            if mode == "normal":
                if is_layer and not self._layer_shell_active:
                    # Layer shell was activated just for stacking — tear down
                    self._teardown_layer_shell()
                elif is_layer:
                    # Layer shell was activated for positioning — can't tear
                    # down without losing position.  Set TOP as neutral.
                    Gtk4LayerShell.set_layer(
                        self, Gtk4LayerShell.Layer.TOP)
                self._flash("Normal stacking")
                return True

            # For above/below: if already a layer window, just switch layer
            if is_layer:
                layer = (Gtk4LayerShell.Layer.TOP if mode == "above"
                         else Gtk4LayerShell.Layer.BOTTOM)
                Gtk4LayerShell.set_layer(self, layer)
                label = "Keep above" if mode == "above" else "Keep below"
                self._flash(label)
                return True

            # Not yet a layer window — can't init after map on most compositors
            # Return False to try other backends
            return False
        except Exception as e:
            print(f"layer-shell stacking: {e}", file=sys.stderr)
            return False

    def _teardown_layer_shell(self):
        """Remove layer-shell by hide/show cycle to get a normal toplevel."""
        try:
            was_playing = True
            _, state, _ = self.pipeline.pipeline.get_state(
                Gst.CLOCK_TIME_NONE // 1000)
            was_playing = (state == Gst.State.PLAYING)

            self.set_visible(False)
            # Re-present as a normal window
            GLib.idle_add(self._reshow_normal, was_playing)
        except Exception as e:
            print(f"layer-shell teardown: {e}", file=sys.stderr)

    def _reshow_normal(self, resume_playing: bool):
        self.set_visible(True)
        self.present()
        if resume_playing:
            self.pipeline.play()
        return False

    def _try_wmctrl_stacking(self, mode: str) -> bool:
        title = self.get_title() or APP_NAME
        try:
            if mode == "above":
                subprocess.run(["wmctrl", "-r", title, "-b", "remove,below"],
                               capture_output=True, timeout=3)
                r = subprocess.run(
                    ["wmctrl", "-r", title, "-b", "add,above"],
                    capture_output=True, timeout=3)
            elif mode == "below":
                subprocess.run(["wmctrl", "-r", title, "-b", "remove,above"],
                               capture_output=True, timeout=3)
                r = subprocess.run(
                    ["wmctrl", "-r", title, "-b", "add,below"],
                    capture_output=True, timeout=3)
            else:
                subprocess.run(["wmctrl", "-r", title, "-b", "remove,above"],
                               capture_output=True, timeout=3)
                r = subprocess.run(
                    ["wmctrl", "-r", title, "-b", "remove,below"],
                    capture_output=True, timeout=3)
            if r.returncode == 0:
                label = {"above": "Keep above", "below": "Keep below"}.get(
                    mode, "Normal stacking")
                self._flash(label)
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return False

    def _try_xdotool_stacking(self, mode: str) -> bool:
        title = self.get_title() or APP_NAME
        try:
            r = subprocess.run(
                ["xdotool", "search", "--name", title],
                capture_output=True, text=True, timeout=3)
            wid = r.stdout.strip().split("\n")[0]
            if not wid:
                return False
            if mode == "above":
                subprocess.run(
                    ["xprop", "-id", wid, "-f", "_NET_WM_STATE", "32a",
                     "-set", "_NET_WM_STATE", "_NET_WM_STATE_ABOVE"],
                    capture_output=True, timeout=3)
            elif mode == "below":
                subprocess.run(
                    ["xprop", "-id", wid, "-f", "_NET_WM_STATE", "32a",
                     "-set", "_NET_WM_STATE", "_NET_WM_STATE_BELOW"],
                    capture_output=True, timeout=3)
            else:
                subprocess.run(
                    ["xprop", "-id", wid, "-remove", "_NET_WM_STATE"],
                    capture_output=True, timeout=3)
            label = {"above": "Keep above", "below": "Keep below"}.get(
                mode, "Normal stacking")
            self._flash(label)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired, IndexError):
            return False

    # ── Volume ──────────────────────────────────────────────────────────

    def _adj_vol(self, delta):
        self.pipeline.volume = self.pipeline.volume + delta
        self._flash(f"Volume {self.pipeline.volume:.0%}")

    def _do_mute(self):
        self.pipeline.toggle_mute()
        v = self.pipeline.volume
        self._flash("Muted" if v == 0 else f"Volume {v:.0%}")

    # ── About ───────────────────────────────────────────────────────────

    def _show_about(self):
        about = Gtk.AboutDialog(transient_for=self, modal=True)
        about.set_program_name(APP_NAME)
        about.set_version(APP_VERSION)
        about.set_comments(
            "Transparent VP9/WebM video overlay player\n"
            "for Wayland & X11.\n\n"
            "Vibe coded with love.")
        about.set_license_type(Gtk.License.LGPL_3_0)
        about.set_authors(["John Boero", "Claude (Anthropic)"])
        about.set_copyright("© 2025 John Boero and Claude (Anthropic)")
        about.set_website("https://github.com")
        about.set_website_label("Source")
        ip = icon_path()
        if os.path.isfile(ip):
            try:
                about.set_logo(Gdk.Texture.new_from_filename(ip))
            except Exception:
                pass
        about.present()

    # ── Actions ─────────────────────────────────────────────────────────

    def _handle_eos(self):
        """On end-of-stream: advance playlist or loop, or exit."""
        if len(self._playlist) > 1:
            # Playlist mode: advance to next file
            self._playlist_idx += 1
            if self._playlist_idx >= len(self._playlist):
                if self._exit_after:
                    self.close()
                    return
                if self._loop:
                    self._playlist_idx = 0
                else:
                    return  # playlist finished, stop
            self._play_current()
        else:
            # Single file: exit, restart if looping, or stop
            if self._exit_after:
                self.close()
            elif self._loop:
                self.pipeline.restart()

    def _current_file(self) -> str:
        return self._playlist[self._playlist_idx]

    def _play_current(self):
        """Switch to the current playlist item and update the title."""
        path = self._current_file()
        name = os.path.basename(path)
        self.pipeline.change_uri(media_uri(path))
        if len(self._playlist) > 1:
            pos = f"{self._playlist_idx + 1}/{len(self._playlist)}"
            self.set_title(f"{name}  [{pos}]")
            self._flash(f"{name}  [{pos}]")
        else:
            self.set_title(APP_NAME)

    def _playlist_next(self):
        """Skip to next file in playlist."""
        if len(self._playlist) <= 1:
            return
        self._playlist_idx = (self._playlist_idx + 1) % len(self._playlist)
        self._play_current()

    def _playlist_prev(self):
        """Skip to previous file in playlist."""
        if len(self._playlist) <= 1:
            return
        self._playlist_idx = (self._playlist_idx - 1) % len(self._playlist)
        self._play_current()

    def _toggle_loop(self):
        self._loop = not self._loop
        self._loop_btn.set_label("🔁" if self._loop else "🔂")
        self._flash(f"Loop {'ON' if self._loop else 'OFF'}")

    def _toggle_frameless(self):
        self._frameless = not self._frameless
        self.set_decorated(not self._frameless)
        self._flash(f"Frame {'OFF' if self._frameless else 'ON'}")

    def _toggle_on_top(self):
        if self._stacking == "above":
            self._set_stacking("normal")
        else:
            self._set_stacking("above")

    def _toggle_maximize(self):
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    def _adjust_opacity(self, delta):
        self._opacity = max(0.1, min(1.0, self._opacity + delta))
        self.set_opacity(self._opacity)
        self._flash(f"Opacity {self._opacity:.0%}")

    def _flash(self, text):
        self._status.set_label(text)
        GLib.timeout_add(1500, lambda: self._status.set_label(""))

    # ── Input callbacks ─────────────────────────────────────────────────

    def _on_realize(self, _w):
        # X11 positioning fallback — if we couldn't use layer-shell and
        # a position was requested, use xdotool to move the window after
        # it's been mapped.  This doesn't work on Wayland (by design).
        if (self._req_position is not None
                and not self._layer_shell_active
                and not is_wayland()):
            x, y = resolve_position(
                self._req_position[0], self._req_position[1],
                self._req_size[0], self._req_size[1])
            # Defer slightly to ensure the window is fully mapped
            GLib.timeout_add(100, self._x11_move_window, x, y)

        self.pipeline.play()

    def _x11_move_window(self, x: int, y: int):
        """Move window on X11 via wmctrl or xdotool."""
        title = self.get_title() or APP_NAME
        try:
            # wmctrl -r <title> -e 0,x,y,-1,-1  (gravity,x,y,w,h)
            subprocess.run(
                ["wmctrl", "-r", title, "-e", f"0,{x},{y},-1,-1"],
                capture_output=True, timeout=3)
        except FileNotFoundError:
            try:
                r = subprocess.run(
                    ["xdotool", "search", "--name", title],
                    capture_output=True, text=True, timeout=3)
                wid = r.stdout.strip().split("\n")[0]
                if wid:
                    subprocess.run(
                        ["xdotool", "windowmove", wid, str(x), str(y)],
                        capture_output=True, timeout=3)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                print(f"Could not move window to {x},{y} — "
                      f"install wmctrl or xdotool", file=sys.stderr)
        except subprocess.TimeoutExpired:
            pass
        return False  # don't repeat the timeout

    def _on_key(self, _ctrl, keyval, _keycode, state):
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        k = Gdk.keyval_name(keyval)
        if k == "space":
            self.pipeline.toggle_pause()
        elif k in ("f", "F"):
            self._toggle_frameless()
        elif k in ("t", "T"):
            self._toggle_on_top()
        elif k == "o" and not shift:
            self._adjust_opacity(self.OPACITY_STEP)
        elif k == "O" or (k == "o" and shift):
            self._adjust_opacity(-self.OPACITY_STEP)
        elif k in ("l", "L"):
            self._toggle_loop()
        elif k in ("r", "R"):
            self.pipeline.restart()
        elif k in ("n", "N", "Right"):
            self._playlist_next()
        elif k in ("p", "P", "Left"):
            self._playlist_prev()
        elif k == "Escape":
            self.close()
        elif k in ("q", "Q") and bool(state & Gdk.ModifierType.CONTROL_MASK):
            self.close()
        elif k == "F4" and bool(state & Gdk.ModifierType.ALT_MASK):
            self.close()
        else:
            return False
        return True

    def _on_dblclick(self, _g, n, _x, _y):
        if n == 2:
            self._toggle_maximize()

    def _on_scroll(self, _c, _dx, dy):
        self._adjust_opacity(-dy * self.OPACITY_STEP)
        return True

    def _on_drag_begin(self, gesture, start_x, start_y):
        native = self.get_native()
        if native is None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        surface = native.get_surface()
        if surface is None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        try:
            result = self.picture.translate_coordinates(
                native, start_x, start_y)
            if result is None:
                wx, wy = start_x, start_y
            elif isinstance(result, tuple) and len(result) == 2:
                wx, wy = result
            else:
                wx, wy = result[-2], result[-1]
        except Exception:
            wx, wy = start_x, start_y
        try:
            surface.begin_move(
                gesture.get_device(), gesture.get_current_button(),
                wx, wy, Gdk.CURRENT_TIME)
        except Exception as e:
            print(f"begin_move: {e}", file=sys.stderr)
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)


# ── CLI Argument Parsing ─────────────────────────────────────────────────────

def parse_position(s: str) -> tuple[int, int]:
    """Parse 'X,Y' position string.  Negative values = from right/bottom."""
    try:
        parts = s.split(",")
        return (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        raise argparse.ArgumentTypeError(
            f"Invalid position '{s}'.  Use X,Y  e.g. 100,200 or -50,-50")


def parse_size(s: str) -> tuple[int, int] | str:
    """Parse 'WxH', 'W,H', or 'max' size string."""
    if s.strip().lower() == "max":
        return "max"
    try:
        for sep in ("x", "X", ","):
            if sep in s:
                parts = s.split(sep)
                return (int(parts[0]), int(parts[1]))
        raise ValueError
    except (ValueError, IndexError):
        raise argparse.ArgumentTypeError(
            f"Invalid size '{s}'.  Use WxH (e.g. 320x240) or 'max'")


# ── Application ──────────────────────────────────────────────────────────────

class OverlayApp(Gtk.Application):
    def __init__(self, playlist: list[str], loop: bool, *,
                 exit_after: bool = False,
                 controls_mode: str = "autohide",
                 position=None, size=(480, 480)):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.playlist = playlist
        self.loop = loop
        self.exit_after = exit_after
        self.controls_mode = controls_mode
        self.position = position
        self.size = size

    def do_startup(self):
        Gtk.Application.do_startup(self)
        register_icon()

    def do_activate(self):
        win = OverlayWindow(
            self, self.playlist,
            loop=self.loop,
            exit_after=self.exit_after,
            controls_mode=self.controls_mode,
            position=self.position,
            size=self.size)
        win.set_icon_name(ICON_NAME)
        win.present()


def main():
    parser = argparse.ArgumentParser(
        description="Transparent VP9/WebM video overlay player for Wayland/X11",
        epilog="Right-click for context menu.  "
               "Space=pause  F=frame  T=on-top  O=opacity  L=loop  "
               "R=restart  N/→=next  P/←=prev",
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument("video", nargs="+",
                        help="One or more VP9+alpha .webm files or URLs (playlist)")
    parser.add_argument("--no-loop", action="store_true",
                        help="Don't loop (default: loop)")
    parser.add_argument("--exit", action="store_true", dest="exit_after",
                        help="Play through playlist once then exit "
                             "(useful for tutorials/learning platforms)")
    parser.add_argument("--hide-controls", action="store_true",
                        help="Start with controls hidden (right-click to show)")
    parser.add_argument("--show-controls", action="store_true",
                        help="Pin controls visible permanently at start")
    parser.add_argument("--position", type=parse_position, default=None,
                        metavar="X,Y",
                        help="Window position.  Negative values offset from "
                             "right/bottom edge.  e.g. 100,200  or  -50,-50")
    parser.add_argument("--size", type=parse_size, default=(480, 480),
                        metavar="WxH",
                        help="Window size (default: 480x480).  e.g. 320x240 "
                             "or 'max' to start maximized")

    args = parser.parse_args()

    # Validate files exist (URLs are accepted without validation)
    playlist = []
    for f in args.video:
        if f.startswith(("http://", "https://")):
            playlist.append(f)
        elif os.path.isfile(f):
            playlist.append(f)
        else:
            print(f"Warning: skipping not found: {f}", file=sys.stderr)
    if not playlist:
        print("Error: no valid video files or URLs provided.", file=sys.stderr)
        sys.exit(1)

    if len(playlist) > 1:
        print(f"Playlist: {len(playlist)} files", file=sys.stderr)

    if args.hide_controls:
        controls = "hidden"
    elif args.show_controls:
        controls = "shown"
    else:
        controls = "autohide"

    GLib.set_prgname(APP_ID)
    GLib.set_application_name(APP_NAME)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    OverlayApp(
        playlist,
        loop=not args.no_loop and not args.exit_after,
        exit_after=args.exit_after,
        controls_mode=controls,
        position=args.position,
        size=args.size,
    ).run([])


if __name__ == "__main__":
    main()
