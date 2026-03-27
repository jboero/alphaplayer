# AlphaPlayer -- Recreation Prompt

Use this document to recreate AlphaPlayer from scratch with an AI coding assistant.

## Summary

AlphaPlayer is a transparent VP9/WebM video overlay player for Linux (Wayland
and X11). It uses GTK4 and GStreamer via PyGObject to render video with alpha
transparency directly on the desktop.

## Core Prompt

> Build a Python desktop application called "AlphaPlayer" that plays VP9 WebM
> videos with alpha transparency as a floating overlay on Linux desktops.
>
> **Stack:** Python 3.10+, GTK4 via PyGObject (`gi`), GStreamer 1.0. No pip-installable
> dependencies -- everything comes from system GObject introspection bindings.
>
> **Video pipeline:** Use GStreamer `playbin3` (fallback to `playbin`) with
> `gtk4paintablesink` (fallback `gtk4sink`) and a `videoconvert` filter. The
> paintable is rendered in a `Gtk.Picture` widget. Support play, pause, restart,
> seek, volume control (0.0-1.5), and mute toggle.
>
> **Transparency:** The GTK4 window must have a fully transparent background
> (CSS `background: transparent` on the window and all children). Only the
> video's non-transparent pixels should be visible.
>
> **Window management:**
> - Frameless by default (undecorated), toggle with 'F' key
> - Draggable by clicking and dragging anywhere on the video
> - Double-click to maximize/restore
> - Adjustable opacity (10%-100%) via 'O'/Shift+O keys and scroll wheel
> - Keep-above / keep-below stacking with three backends:
>   1. `gtk4-layer-shell` (preferred, Wayland-native)
>   2. `wmctrl` (X11/XWayland)
>   3. `xdotool` + `xprop` (X11 fallback)
> - Window positioning via `--position X,Y` (negative values offset from
>   screen right/bottom edges)
> - Window sizing via `--size WxH` or `--size max` for maximized
>
> **Playlist support:**
> - Accept multiple files and HTTP/HTTPS URLs as arguments
> - Auto-advance to next file on end-of-stream
> - N/Right and P/Left to navigate manually
> - Loop entire playlist by default (`--no-loop` to disable)
> - `--exit` flag: play through once then quit (for tutorials)
>
> **Controls:**
> - Auto-hiding control bar at the bottom (5s timeout, semi-transparent dark
>   background with rounded corners)
> - Buttons: play/pause, restart, loop toggle, frameless toggle, on-top toggle,
>   opacity display
> - Right-click context menu with all actions
> - Controls modes: `--hide-controls` (hidden until right-click),
>   `--show-controls` (always visible), default auto-hide on pointer leave
>
> **Keyboard shortcuts:** Space (pause), F (frame), T (on-top), O/Shift+O
> (opacity), L (loop), R (restart), N/Right (next), P/Left (prev),
> Escape/Ctrl+Q/Alt+F4 (quit).
>
> **Desktop integration:**
> - `.desktop` file with `video/webm` MIME type
> - WebP icon converted to PNG at runtime for GTK4 icon theme compatibility
> - Application ID: `io.github.alphaplayer`
>
> **Packaging:**
> - `pyproject.toml` with setuptools backend
> - Entry points: `alphaplayer` (console) and `alphaplayer-gui` (GUI)
> - `python -m alphaplayer` support via `__main__.py`
> - RPM spec file for Fedora COPR
> - LGPL-3.0-or-later license

## Architecture

```
alphaplayer/
├── alphaplayer/
│   ├── __init__.py          # Exports __version__ and main
│   ├── __main__.py          # python -m entry point
│   ├── app.py               # All application code (~1160 lines)
│   └── alphaplayer_icon.webp
├── alphaplayer.desktop
├── alphaplayer.spec
├── pyproject.toml
├── MANIFEST.in
├── LICENSE
└── README.md
```

Everything lives in a single `app.py` with three classes:
- **`VideoPipeline`** -- GStreamer pipeline management
- **`OverlayWindow(Gtk.ApplicationWindow)`** -- transparent window, controls, input handling
- **`OverlayApp(Gtk.Application)`** -- application lifecycle

Plus utility functions for URI handling, screen size detection, icon registration,
position resolution, and Wayland detection.

## Key Implementation Details

- GTK4 CSS warnings are suppressed via a custom `GLib.log_set_writer_func` filter.
- The icon is a WebP file bundled as package data; at startup it's decoded to
  PNG and installed into a temp hicolor icon theme directory so GTK4 can find it.
- Wayland detection checks `GDK_BACKEND`, `WAYLAND_DISPLAY`, and
  `XDG_SESSION_TYPE` environment variables.
- `media_uri()` passes through `http://`/`https://`/`file://` URIs and prepends
  `file://` only for bare local paths.
- Stacking control tries gtk4-layer-shell first, then wmctrl, then xdotool+xprop,
  logging which backend is active.
- The `--exit` flag implies `--no-loop` and calls `self.close()` on the final EOS.

## Dependencies

**System (not pip-installable):**
- `python3-gobject`, `gtk4`, `gstreamer1-plugins-base`, `gstreamer1-plugins-good`,
  `gstreamer1-plugin-gtk4`

**Optional:** `gtk4-layer-shell`, `wmctrl`, `xdotool`, `xprop`
