# VT-Ragnaros

A reverse-engineered, from-scratch Linux driver and daemon for the **Ragnaros USB control deck** - a Linux-native alternative to the vendor's Windows software.

The daemon renders icons and animated GIFs onto the deck's LCD keys and touch strip, and executes configurable shell commands on every input event.

## Features

- **10 LCD keys** (2x5 grid, 112x112 px each) with static icons or animated GIFs
- **4 rotary knobs** with rotate (CW/CCW) and press actions, with detent debouncing
- **4-segment LCD touch strip** (704x124 combined): taps and swipes are real inputs,
  and it shows now playing, a system dashboard, desktop notifications or idle GIFs
- **Key layers** - a second set of keys over the same profile, on a knob press
- **Hot profile switching** from a key, a swipe or the CLI
- **`ragnarosctl`** - a control socket for scripts, shortcuts and CI
- **Desktop aware** - toasts on the strip, and the deck goes dark when the session locks
- **YAML keymap profiles** mapping any input to a shell command
- Runs as a **systemd user service**

## How It Works

The vendor protocol was reverse-engineered from the Windows `SDLibrary1.dll` - no vendor SDK is used.

```
ragnarosd.py ──> protocol.py ──(ctypes / libusb-1.0)──> Ragnaros deck
     │                JPEG frames in 1024-byte chunks to display slots
     ├── renderer.py ── PIL: icons / GIFs -> JPEG
     ├── inputmap.py ── HID input reports -> key / knob / strip events
     └── profiles/*.yaml ── events -> shell commands
```

- Output: images sent as JPEG payloads over bulk endpoint with a `CRT` command header; keys map to display slots 5-14, strip segments to 0-3 (content rotated 180°)
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
2. Installs udev rules (hidraw permissions, `plugdev` group) and a `usbhid` kernel quirk for the device - **requires sudo and one reboot**
3. Installs and enables the `ragnarosd.service` systemd user unit
4. Installs Python dependencies (`pillow`, `pyyaml`) if missing

Then start it:

```bash
systemctl --user start ragnarosd
```

## Profiles

Profiles live in `profiles/` as YAML files. Bundled: `streaming` (default), `work`, `ai-tools`, `stream` (OBS) and `system` - a dashboard tab whose strip stays on the metrics and whose first four keys pick which cards it shows.

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

Keys accept `action` (a shell command or a deck verb), `profile` (hot switch),
`layer` (momentary while held) or `layer_toggle`. The deck verbs are `pomodoro`,
`dashboard[:cards]`, `obs:*`, `profile:<name>` and `layer:<name>`.

`action: dashboard:cpu,ram,temp,gpu` pins that set of cards on the strip; pressing
the same key again puts the strip back. `strip.pinned: dashboard` does it for a
whole profile, which is what `system.yaml` uses.

### The strip

Priority, top to bottom: a transient overlay (knob feedback, a toast), then a
pinned dashboard, then now playing, then the idle face. After ~10 s of inactivity
the idle face alternates between the segment GIFs and the dashboard every 60 s
(`strip.idle_seconds`). A profile with `strip.pinned: dashboard` never rotates.

```yaml
strip:
  segments: [gifs/segments/gojo.gif, ...]   # one GIF per 176x124 panel
  pinned: dashboard                         # this profile owns the strip
  idle: [gifs, dashboard]                   # idle rotation (default: both)
  idle_seconds: 60                          # how long each face holds the strip
  dashboard: [clock, cpu, ram, temp]        # gpu, disk, net, battery, uptime
  players:
    ignore: [chromium, brave]               # keep browser tabs off the strip
  touch:
    "3": dashboard                          # per-panel tap actions
  swipe:
    left: profile:work
    right: profile:streaming
```

Without a `touch` mapping, tapping the last panel pins or unpins the dashboard
and, while music plays, the first three panels are play/pause, previous and next
- they sit right under the art, title and artist cards. A swipe cycles profiles.

### Layers

A layer lays a second set of keys over the profile; keys it does not define fall
through to the base. The bundled profiles put a `media` layer on knob 2's press.

```yaml
layers:
  media:
    keys:
      "0": {icon: icons/media_prev.png, action: playerctl previous}
      "9": {icon: icons/layers.png, layer_toggle: media}   # back to base
```

### Notifications

Desktop notifications are read off the session bus with `dbus-monitor` and shown
as a 4 s card. Mute them per profile:

```yaml
notifications:
  enabled: true
  seconds: 4
  ignore: [Spotify, Thunderbird]
```

## Control CLI

`ragnarosctl` talks to the running daemon over a unix socket
(`$XDG_RUNTIME_DIR/ragnaros.sock`, mode 0600), so shortcuts, scripts and CI can
drive the deck:

```bash
ragnarosctl status                       # profile, layer, what the strip shows
ragnarosctl profile work                 # or: next, prev, list
ragnarosctl layer media                  # or: base, list
ragnarosctl dashboard toggle             # or: on, off, "cpu,ram,temp,gpu"
ragnarosctl brightness 40
ragnarosctl toast "Build passed" "12 tests, 4.2s" --app=ci --seconds=6
ragnarosctl key 6                        # run a key's action without touching it
ragnarosctl alert "Claude terminó" "VT-Ragnaros"   # holds until you press a key
ragnarosctl alert --clear
ragnarosctl watch [--grab]               # stream every input as JSON
```

Add `--json` for machine-readable replies.

### Notices that wait for you

A toast is gone in four seconds; an **alert** owns the strip until someone
presses a key on the deck, and the last card counts how long it has been
waiting. That is the shape of "come back and look at this".

The bundled `tools/claude_hook.py` is a Claude Code `Stop` hook: when a session
finishes, the deck shows the project and the last thing Claude said for eight
seconds, then hands the strip back to the GIFs or the dashboard. Set
`RAGNAROS_CLAUDE_HOOK_MODE=alert` to make it an alert that waits instead, and
`RAGNAROS_CLAUDE_HOOK_SECONDS` to change how long the toast stays.

```json
{ "hooks": { "Stop": [ { "hooks": [ {
  "type": "command",
  "command": "python3 ~/path/to/VT-Ragnaros/tools/claude_hook.py"
} ] } ] } }
```

It exits 0 whatever happens, so a stopped daemon or an unplugged deck never
breaks the session. Registered as a `Notification` hook instead, it raises the
notice when Claude is waiting for a permission answer.

### Scripts can take the deck

`ragnarosctl watch` keeps its connection open and prints one JSON line per
input, so a long-running script can react to the deck instead of launching
one-shot commands:

```bash
ragnarosctl watch --json | while read -r event; do
  case "$(jq -r '.type + ":" + (.index|tostring)' <<<"$event")" in
    key:4) ./deploy.sh ;;
    strip_swipe:1) ./next-take.sh ;;
  esac
done
```

`--grab` additionally suppresses the profile's own actions while the script is
connected, so the deck becomes a blank input device; the grab is released the
moment the client disconnects. Profile switches, layer changes and alerts are
published on the same stream.

## Tools

- `tools/gen_assets.py` - generates 112x112 key icons (Font Awesome glyphs + app icons), including animated tiles
- `tools/process_strip_gif.py` - converts GIFs to the 704x124 strip format
- `tools/ragnarosctl` - control CLI for the running daemon
- `tools/preview_strip.py` - renders the strip frames to a PNG with the bezels marked, to judge layout without the deck
- `tools/strip_order.py` - paints 1 2 3 4 on the panels to confirm their physical order
- `tools/claude_hook.py` - Claude Code Stop hook: raises a deck notice when a session finishes
- `tools/probe_modes.py` - walks the firmware's undocumented MOD command, dumping the feature and input reports at each step. Findings so far: modes 0-9 change no reported state and never break input, and every feature report (0-3) and input report 1 return the same firmware string, `V3.SS_552.02.009` - a version identifier, not device state
- `tools/sniff.py`, `handshake.py`, `probe*.py`, `wake.py`, `listen.py`, `paint*.py` - reverse-engineering and protocol discovery utilities

## Requirements

- Python 3 with `pillow` and `pyyaml`
- `libusb-1.0` (loaded via ctypes, no Python binding needed)
- Linux: udev rules, usbhid quirk, systemd user units
- `playerctl`, `wpctl`, `brightnessctl` for the bundled actions
- `dbus-monitor` (Debian: `dbus-bin`) for toasts and lock dimming - optional

## License

TBD
