# VT-Ragnaros

A reverse-engineered, from-scratch Linux driver and daemon for the **Ragnaros USB control deck** — a Linux-native alternative to the vendor's Windows software.

The daemon renders icons and animated GIFs onto the deck's LCD keys and touch strip, and executes configurable shell commands on every input event.

## Features

- **10 LCD keys** (2x5 grid, 112x112 px each) with static icons or animated GIFs
- **4 rotary knobs** with rotate (CW/CCW) and press actions, with detent debouncing
- **4-segment LCD touch strip** (704x124 combined) that plays idle GIF animations
- **Hot profile switching** directly from a key
- **YAML keymap profiles** mapping any input to a shell command
- Runs as a **systemd user service**

## How It Works

The vendor protocol was reverse-engineered from the Windows `SDLibrary1.dll` — no vendor SDK is used.

```
ragnarosd.py ──> protocol.py ──(ctypes / libusb-1.0)──> Ragnaros deck
     │                JPEG frames in 1024-byte chunks to display slots
     ├── renderer.py ── PIL: icons / GIFs -> JPEG
     ├── inputmap.py ── HID input reports -> key / knob / strip events
     └── profiles/*.yaml ── events -> shell commands
```

- Output: images sent as JPEG payloads over bulk endpoint with a `CRT` command header; keys map to display slots 5–14, strip segments to 0–3 (content rotated 180°)
- Input: reports polled from EP `0x82`, decoded into `key`, `knob`, `knob_press`, `strip_touch`, and `strip_swipe` events

## Installation

Requires Linux with `libusb-1.0`, `udev`, and `systemd`.

```bash
git clone https://github.com/ValentinTorassa/VT-Ragnaros
cd VT-Ragnaros
./install.sh
```

The installer:

1. Symlinks `daemon/`, `profiles/`, and `assets/` into `~/.config/ragnaros`
2. Installs udev rules (hidraw permissions, `plugdev` group) and a `usbhid` kernel quirk for the device — **requires sudo and one reboot**
3. Installs and enables the `ragnarosd.service` systemd user unit
4. Installs Python dependencies (`pillow`, `pyyaml`) if missing

Then start it:

```bash
systemctl --user start ragnarosd
```

## Profiles

Profiles live in `profiles/` as YAML files. Bundled: `streaming` (default), `work`, `ai-tools`.

Each profile maps 10 keys and 4 knobs to actions, plus optional idle strip GIFs:

```yaml
name: streaming
strip:
  segments:
    - gifs/segments/gojo.gif
    - gifs/segments/yuta.gif
keys:
  "0":
    icon: icons/brave.png
    action: gtk-launch com.brave.Browser
  "6":
    icon: icons/mic_mute.png
    action: wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle
  "9":
    icon: icons/work.png
    profile: work        # switch to another profile
knobs:
  "0":
    rotate:
      cw: wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+
      ccw: wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-
    press: wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle
```

Keys accept either `action` (shell command) or `profile` (hot switch). After ~10 s of inactivity, the strip plays its idle GIF loop.

## Tools

- `tools/gen_assets.py` — generates 112x112 key icons (Font Awesome glyphs + app icons), including animated tiles
- `tools/process_strip_gif.py` — converts GIFs to the 704x124 strip format
- `tools/sniff.py`, `handshake.py`, `probe*.py`, `wake.py`, `listen.py`, `paint*.py` — reverse-engineering and protocol discovery utilities

## Requirements

- Python 3 with `pillow` and `pyyaml`
- `libusb-1.0` (loaded via ctypes, no Python binding needed)
- Linux: udev rules, usbhid quirk, systemd user units

## License

TBD
