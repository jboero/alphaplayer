# AlphaPlayer

A lightweight transparent video overlay player for Linux. Plays VP9/WebM videos
with alpha transparency directly on your desktop, supporting both Wayland and X11.

![License](https://img.shields.io/badge/license-LGPL--3.0-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)

## What It Does

AlphaPlayer renders video with a transparent background so the content floats
over your desktop. Use it for animated mascots, streaming overlays, HUDs,
transparent tutorials, or anything else that benefits from video composited
on top of your workspace.

[demo.webm](https://github.com/user-attachments/assets/0c11a6d7-6598-4d95-a410-557efe92ec46)


**Key features:**
- True alpha transparency via VP9 alpha channel in WebM containers
- Wayland-native positioning and stacking via `gtk4-layer-shell`
- X11/XWayland support via `wmctrl`/`xdotool` fallbacks
- Playlist support with auto-advance
- HTTP/HTTPS URL streaming (local files and remote URLs)
- `--exit` mode for tutorials that play through then close
- Adjustable window opacity (10%-100%)
- Keep-above / keep-below stacking
- Frameless, draggable, auto-hiding controls
- Keyboard shortcuts and right-click context menu
- Desktop integration (`.desktop` file, MIME type `video/webm`)

## Installation

### PyPI

```bash
pip install alphaplayer
```

### Fedora / COPR

```bash
dnf copr enable jboero/alphaplayer
dnf install alphaplayer
```

### From source

```bash
git clone https://github.com/jboero/alphaplayer.git
cd alphaplayer
pip install .
```

## System Dependencies

AlphaPlayer uses GStreamer and GTK4 via PyGObject. These are system libraries
and cannot be installed via pip.

**Required:**
- `python3-gobject` (PyGObject)
- `gtk4`
- `gstreamer1-plugins-base` (videoconvert)
- `gstreamer1-plugins-good` (VP9 decoder, HTTP source)
- `gstreamer1-plugin-gtk4` (GTK4 video sink)

**Optional (recommended):**
- `gtk4-layer-shell` -- Wayland keep-above/below and positioning
- `wmctrl` -- X11/XWayland stacking control
- `xdotool`, `xprop` -- X11 fallback positioning

On Fedora:
```bash
dnf install python3-gobject gtk4 gstreamer1-plugins-base gstreamer1-plugins-good \
    gstreamer1-plugin-gtk4 gtk4-layer-shell wmctrl xdotool xprop
```

## Usage

```bash
# Play a local file
alphaplayer video.webm

# Stream from a URL
alphaplayer https://example.com/overlay.webm

# Position near bottom-right, custom size
alphaplayer --position -50,-50 --size 320x240 mascot.webm

# Playlist of multiple files
alphaplayer intro.webm main.webm outro.webm

# Play through a tutorial then exit automatically
alphaplayer --exit lesson1.webm lesson2.webm lesson3.webm

# Start maximized, no controls
alphaplayer --size max --hide-controls background.webm

# Run as a module
python -m alphaplayer video.webm
```

### Command-Line Options

| Option | Description |
|---|---|
| `video` | One or more `.webm` files or HTTP/HTTPS URLs |
| `--no-loop` | Don't loop (default: loop continuously) |
| `--exit` | Play through playlist once then exit |
| `--hide-controls` | Start with controls hidden (right-click to show) |
| `--show-controls` | Pin controls visible permanently |
| `--position X,Y` | Window position; negative values offset from right/bottom edge |
| `--size WxH` | Window size (default: `480x480`), or `max` to start maximized |

### Keyboard Shortcuts

| Key | Action |
|---|---|
| Space | Toggle pause |
| F | Toggle frameless mode |
| T | Toggle always-on-top |
| O / Scroll Up | Increase opacity |
| Shift+O / Scroll Down | Decrease opacity |
| L | Toggle loop |
| R | Restart video |
| N / Right Arrow | Next in playlist |
| P / Left Arrow | Previous in playlist |
| Double-click | Maximize / restore |
| Right-click | Context menu |
| Escape / Ctrl+Q | Quit |

## Creating Transparent Videos

AlphaPlayer requires VP9 video with alpha channel in a WebM container. You can
create these with FFmpeg:

```bash
# From a video with green screen (chroma key to alpha)
ffmpeg -i input.mp4 \
  -vf "chromakey=0x00ff00:0.1:0.2,format=yuva420p" \
  -c:v libvpx-vp9 -auto-alt-ref 0 -pix_fmt yuva420p \
  output.webm

# From a PNG image sequence with alpha
ffmpeg -framerate 30 -i frames/%04d.png \
  -c:v libvpx-vp9 -auto-alt-ref 0 -pix_fmt yuva420p \
  output.webm
```

## License

LGPL-3.0-or-later. See [LICENSE](LICENSE).

## Credits

- **John Boero** -- author
- **Claude (Anthropic)** -- co-author

> **Vibe code notice:** This project was developed with substantial assistance
> from Claude, Anthropic's AI assistant. The code, packaging, and documentation
> were collaboratively written by a human and an AI. Please review before using
> in critical environments.
