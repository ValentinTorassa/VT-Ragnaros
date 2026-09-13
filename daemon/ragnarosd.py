#!/usr/bin/env python3
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import yaml
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import control
import dbuswatch
import metrics
import protocol
import renderer

try:
    import obsclient
except ImportError:
    obsclient = None

CONFIG_DIR = os.environ.get("RAGNAROS_CONFIG", os.path.expanduser("~/.config/ragnaros"))
STATE_DIR = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
USAGE_LOG = os.environ.get(
    "RAGNAROS_USAGE_LOG", os.path.join(STATE_DIR, "ragnaros", "usage.jsonl"))
IDLE_SECONDS = float(os.environ.get("RAGNAROS_IDLE_SECONDS", "10"))
STATE_POLL = 2.0
OVERLAY_SECONDS = 1.5
SEGMENT_ROTATE_SECONDS = 30.0
STRIP_JPEG_QUALITY = 80
# how long each idle face (GIFs, dashboard) holds the strip before the next one;
# long enough that it never swaps while you are reading it
IDLE_FACE_SECONDS = float(os.environ.get("RAGNAROS_IDLE_FACE_SECONDS", "60"))
DASHBOARD_REFRESH = 1.0
TOAST_SECONDS = 4.0
DEFAULT_IDLE_FACES = ("gifs", "dashboard")

POMO_FOCUS = 25 * 60
POMO_BREAK = 5 * 60


def profile_path(name):
    return os.path.join(CONFIG_DIR, "profiles", f"{name}.yaml")


def load_profile(name):
    path = profile_path(name)
    with open(path) as f:
        profile = yaml.safe_load(f)
    profile["_name"] = name
    return profile


def saved_profile_name():
    try:
        with open(os.path.join(STATE_DIR, "ragnaros", "profile")) as f:
            name = f.read().strip()
        if name and os.path.exists(profile_path(name)):
            return name
    except OSError:
        pass
    return "streaming"


def save_profile_name(name):
    try:
        os.makedirs(os.path.join(STATE_DIR, "ragnaros"), exist_ok=True)
        with open(os.path.join(STATE_DIR, "ragnaros", "profile"), "w") as f:
            f.write(name)
    except OSError:
        pass


def available_profiles():
    directory = os.path.join(CONFIG_DIR, "profiles")
    try:
        return sorted(f[:-5] for f in os.listdir(directory) if f.endswith(".yaml"))
    except OSError:
        return []


def validate_profile(profile, config_dir):
    """Return a list of human-readable problems with a profile dict."""
    issues = []
    assets = os.path.join(config_dir, "assets")

    def asset_exists(rel):
        return os.path.exists(os.path.join(assets, rel))

    for key, spec in (profile.get("keys") or {}).items():
        where = f"{profile.get('_name', '?')}: keys.{key}"
        try:
            k = int(key)
        except (TypeError, ValueError):
            issues.append(f"{where}: key index is not an integer")
            continue
        if not 0 <= k <= 9:
            issues.append(f"{where}: key index outside 0-9")
        if not (spec.get("action") or spec.get("profile")):
            issues.append(f"{where}: no action or profile")
        icon = spec.get("icon")
        if icon and not asset_exists(icon):
            issues.append(f"{where}: missing asset {icon}")
    for name, layer in (profile.get("layers") or {}).items():
        for key, spec in (layer.get("keys") or {}).items():
            icon = spec.get("icon")
            if icon and not asset_exists(icon):
                issues.append(f"{profile.get('_name', '?')}: layers.{name}.{key}: "
                              f"missing asset {icon}")
    for gif in (profile.get("strip") or {}).get("segments") or []:
        if not asset_exists(gif):
            issues.append(f"{profile.get('_name', '?')}: strip missing asset {gif}")
    return issues


def run_action(action):
    if not action:
        return
    if isinstance(action, list):
        for cmd in action:
            run_action(cmd)
        return
    try:
        subprocess.Popen(
            shlex.split(action),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        print(f"action failed: {action!r}: {error}", file=sys.stderr)


class Deck:
    def __init__(self):
        self.dev = None
        self._wait_for_device()
        self.profile = load_profile(saved_profile_name())
        self.last_activity = time.monotonic()
        self.idle_playing = False
        self.gif_next = 0.0
        self.gif_index = 0
        self.key_anims = {}
        self.knob_last = {}
        self.state_next = 0.0
        self.mic_muted = None
        self.mic_key = None
        self.pomo_key = None
        self.pomo = None
        self.pomo_next = 0.0
        self.player = None
        self.np_next = 0.0
        self.obs_state = None
        self.obs_keys = {}
        self.obs_next_try = 0.0
        self.obs_warn_next = 0.0
        self.keepalive_next = 0.0
        self.overlay_until = 0.0
        self.seg_rotate_next = 0.0
        self.metrics = metrics.Metrics()
        self.control = None
        self.dbus = None
        self.layer = None
        self.layer_hold = None
        self.pinned = None
        self.dash_cards = None
        self.alert = None
        self.alert_next = 0.0
        self.locked = False
        self.brightness = 100
        self.dash_next = 0.0
        self.idle_face = None
        self.idle_face_next = 0.0
        self._loop_cache = {}
        self._icon_cache = {}
        self._last_toast = ("", 0.0)
        self._art_url = None
        self._art_img = None
        self._profile_mtime = self._mtime()

    def asset(self, rel):
        return os.path.join(CONFIG_DIR, "assets", rel)

    def _wait_for_device(self):
        """Block until the deck can be opened; recovers automatically on replug."""
        announced = False
        while True:
            try:
                self.dev = protocol.Ragnaros()
                if announced:
                    print("ragnaros: device attached, resuming", file=sys.stderr)
                return
            except RuntimeError as error:
                if "libusb-1.0 is required" in str(error):
                    sys.exit(f"Ragnaros unavailable: {error}")
                if not announced:
                    print(f"ragnaros: {error}; waiting for the device to appear",
                          file=sys.stderr)
                    announced = True
                time.sleep(1)

    def _mtime(self):
        try:
            return os.path.getmtime(profile_path(self.profile["_name"]))
        except (KeyError, OSError):
            return None

    # -- layers --------------------------------------------------------------
    def layers(self):
        return self.profile.get("layers") or {}

    def active_keys(self):
        """Base keys with the active layer laid over them, by key index."""
        keys = dict(self.profile.get("keys") or {})
        keys.update((self.layers().get(self.layer) or {}).get("keys") or {})
        return keys

    def active_knobs(self):
        knobs = dict(self.profile.get("knobs") or {})
        knobs.update((self.layers().get(self.layer) or {}).get("knobs") or {})
        return knobs

    def set_layer(self, name):
        if name in (None, "", "base"):
            name = None
        elif name not in self.layers():
            return False
        if name != self.layer:
            self.layer = name
            self.paint_keys()
            self.publish("layer", name=self.layer or "base")
        return True

    # -- painting ------------------------------------------------------------
    def _icon_jpeg(self, path):
        if path not in self._icon_cache:
            self._icon_cache[path] = renderer.to_jpeg(
                renderer.load_icon(path, protocol.KEY_LCD, protocol.ROTATION))
        return self._icon_cache[path]

    def _loop(self, kind, path, build):
        """Encoded frames are kept per asset: repaints and layer switches are free."""
        if (kind, path) not in self._loop_cache:
            self._loop_cache[(kind, path)] = build(path)
        return self._loop_cache[(kind, path)]

    def paint_keys(self):
        keys = self.active_keys()
        self.key_anims = {}
        for key, spec in keys.items():
            icon = spec.get("icon")
            path = self.asset(icon) if icon else None
            if not path or not os.path.exists(path):
                continue
            if path.endswith(".gif"):
                frames = self._loop("key", path, lambda p: [
                    (renderer.to_jpeg(f), d) for f, d in
                    renderer.gif_frames(p, protocol.KEY_LCD, protocol.ROTATION)])
                if frames:
                    self.key_anims[int(key)] = [frames, 0, 0.0]
            else:
                self.dev.send_image(int(key), self._icon_jpeg(path))
                self.dev.flush()
        self.mic_key = next(
            (int(k) for k, spec in keys.items()
             if isinstance(spec.get("action"), str)
             and "@DEFAULT_AUDIO_SOURCE@" in spec["action"] and "set-mute" in spec["action"]),
            None)
        self.pomo_key = next(
            (int(k) for k, spec in keys.items() if spec.get("action") == "pomodoro"), None)
        self.obs_keys = {int(k): spec["action"] for k, spec in keys.items()
                         if isinstance(spec.get("action"), str)
                         and spec["action"].startswith("obs:")}
        self.repaint_mic()
        self.repaint_pomo()
        self.repaint_obs()

    def apply_profile(self):
        self.overlay_until = 0.0
        self.layer = None
        self.layer_hold = None
        # a profile can own the strip outright: strip.pinned: dashboard
        self.pinned = "dashboard" if self.strip_config("pinned") == "dashboard" else None
        self.dash_cards = None
        self._profile_mtime = self._mtime()
        for issue in validate_profile(self.profile, CONFIG_DIR):
            print(f"ragnaros: profile issue: {issue}", file=sys.stderr)
        self.paint_keys()
        self.idle_playing = False
        self.idle_face = None
        self.last_activity = time.monotonic() - IDLE_SECONDS
        self.strip_tick(time.monotonic())

    def switch_profile(self, name):
        self.profile = load_profile(name)
        save_profile_name(name)
        self.apply_profile()
        self.publish("profile", name=name)

    def maybe_reload_profile(self):
        m = self._mtime()
        if m is None or self._profile_mtime is None or m == self._profile_mtime:
            return
        print(f"ragnaros: {self.profile.get('_name')}.yaml changed, hot-reloading",
              file=sys.stderr)
        try:
            self.profile = load_profile(self.profile["_name"])
            self.apply_profile()
        except Exception as error:
            print(f"ragnaros: hot-reload failed, keeping previous profile: {error}",
                  file=sys.stderr)

    def log_usage(self, event, action):
        try:
            os.makedirs(os.path.dirname(USAGE_LOG), exist_ok=True)
            with open(USAGE_LOG, "a") as f:
                f.write(json.dumps({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "profile": self.profile.get("name") or "unknown",
                    "kind": event[0],
                    "idx": event[1],
                    "value": event[2],
                    "action": action,
                }) + "\n")
        except OSError:
            pass

    def publish(self, kind, **fields):
        """Push one event to every `ragnarosctl watch` subscriber."""
        if self.control:
            self.control.broadcast({"type": kind, "profile": self.profile.get("_name"),
                                    "layer": self.layer or "base", **fields})

    def set_alert(self, app, summary, body=""):
        """A notice that owns the strip until someone acknowledges it."""
        self.alert = {"app": app, "summary": summary, "body": body,
                      "since": time.monotonic()}
        self.alert_next = 0.0
        self.publish("alert", app=app, summary=summary, body=body, state="raised")

    def clear_alert(self):
        if not self.alert:
            return False
        waited = time.monotonic() - self.alert["since"]
        self.publish("alert", app=self.alert["app"], summary=self.alert["summary"],
                     state="cleared", waited=round(waited, 1))
        self.alert = None
        self.dash_next = self.np_next = self.gif_next = 0.0
        return True

    def wake_strip(self):
        """A real press pulls the strip out of its idle face."""
        self.idle_playing = False
        self.idle_face = None

    def run_deck_action(self, action):
        """Run a key/touch/swipe action: deck verbs first, shell otherwise."""
        if action == "pomodoro":
            self.pomo_press()
        elif isinstance(action, str) and action.split(":")[0] == "dashboard":
            names = action.partition(":")[2].replace(",", " ").split()
            self.toggle_dashboard(cards=names or None)
        elif isinstance(action, str) and action.startswith("obs:"):
            self.obs_action(action)
        elif isinstance(action, str) and action.startswith("profile:"):
            self.switch_profile(action.split(":", 1)[1])
        elif isinstance(action, str) and action.startswith("layer:"):
            target = action.split(":", 1)[1] or None
            self.set_layer(None if self.layer == target else target)
        else:
            run_action(action)

    def cycle_profile(self, direction):
        names = available_profiles()
        if not names:
            return
        try:
            index = names.index(self.profile.get("_name"))
        except ValueError:
            index = 0
        self.switch_profile(names[(index + direction) % len(names)])

    def handle_event(self, event):
        self.last_activity = time.monotonic()
        kind, idx, value = event
        self.publish(kind, index=idx, value=value)
        if value and kind in ("key", "knob_press", "strip_touch") and self.clear_alert():
            return  # the press that dismisses a notice does nothing else
        if self.control and self.control.grabbed():
            return  # a `watch --grab` client owns the inputs
        if kind == "key":
            spec = self.active_keys().get(str(idx)) or {}
            if not value:
                if self.layer_hold == idx:  # momentary layer ends with the press
                    self.layer_hold = None
                    self.set_layer(None)
                return
            self.wake_strip()
            if "layer" in spec:
                self.layer_hold = idx
                self.log_usage(event, f"layer:{spec['layer']}")
                self.set_layer(spec["layer"])
                return
            if "layer_toggle" in spec:
                target = spec["layer_toggle"]
                self.log_usage(event, f"layer_toggle:{target}")
                self.set_layer(None if self.layer == target else target)
                return
            if "profile" in spec:
                self.log_usage(event, f"switch:{spec['profile']}")
                self.switch_profile(spec["profile"])
                return
            action = spec.get("action")
            self.log_usage(event, action)
            self.run_deck_action(action)
        elif kind == "knob":
            # the device bursts several reports per detent; act on one per 120ms
            now = time.monotonic()
            token = (idx, value > 0)
            if now - self.knob_last.get(token, 0) < 0.12:
                return
            self.knob_last[token] = now
            self.wake_strip()
            spec = self.active_knobs().get(str(idx)) or {}
            rotate = spec.get("rotate")
            if isinstance(rotate, dict):
                action = rotate.get("cw" if value > 0 else "ccw")
                self.log_usage(event, action)
                run_action(action)
                if isinstance(action, str):
                    if "set-volume" in action and "@DEFAULT_AUDIO_SINK@" in action:
                        self.show_overlay("volume")
                    elif "brightnessctl set" in action:
                        self.show_overlay("brightness")
        elif kind == "knob_press":
            spec = self.active_knobs().get(str(idx)) or {}
            if not value:
                return
            self.wake_strip()
            self.log_usage(event, spec.get("press"))
            self.run_deck_action(spec.get("press"))
        elif kind == "strip_touch" and value:
            self.strip_touch(idx, event)
        elif kind == "strip_swipe":
            self.strip_swipe(idx, event)

    def strip_config(self, key, default=None):
        return (self.profile.get("strip") or {}).get(key, default)

    def strip_touch(self, idx, event):
        """Tap a panel: profile mapping first, then the card under the finger."""
        self.wake_strip()
        action = (self.strip_config("touch") or {}).get(str(idx))
        if action:
            self.log_usage(event, action)
            self.run_deck_action(action)
            return
        if idx == 3 or self.pinned == "dashboard":
            # the rightmost card is the dashboard handle in both directions
            self.log_usage(event, "dashboard")
            self.toggle_dashboard()
            return
        if self.player:  # the cards are art / title / artist: play, prev, next
            action = {0: "playerctl play-pause", 1: "playerctl previous",
                      2: "playerctl next"}[idx]
            self.log_usage(event, action)
            run_action(action)

    def strip_swipe(self, direction, event):
        self.wake_strip()
        action = (self.strip_config("swipe") or {}).get(
            "right" if direction > 0 else "left")
        if action:
            self.log_usage(event, action)
            self.run_deck_action(action)
            return
        self.log_usage(event, f"profile:{'next' if direction > 0 else 'prev'}")
        self.cycle_profile(1 if direction > 0 else -1)

    STRIP_FULL = (protocol.STRIP_LCD[0] * 4, protocol.STRIP_LCD[1])

    def push_strip_frame(self, frame):
        """Split an upright 704x124 frame across the four strip panels.

        Every panel is mounted upside down, so each crop is rotated on
        its own: rotating the whole frame first would also reverse the
        panel order, since slot 0 is the leftmost segment.
        """
        w, h = protocol.STRIP_LCD
        for seg in range(4):
            part = frame.crop((seg * w, 0, (seg + 1) * w, h)).rotate(protocol.ROTATION)
            data = renderer.to_jpeg(part, quality=STRIP_JPEG_QUALITY)
            self.dev.send_image(seg, data, strip=True)
            self.dev.flush()  # strip segments only display when flushed per image

    def idle_gifs(self):
        gifs = self.strip_config("gif", "gifs/nanami.gif")
        return [gifs] if isinstance(gifs, str) else gifs

    def idle_segments(self):
        segs = self.strip_config("segments")
        return segs[:4] if segs else None

    def idle_face_seconds(self):
        try:
            return max(3.0, float(self.strip_config("idle_seconds", IDLE_FACE_SECONDS)))
        except (TypeError, ValueError):
            return IDLE_FACE_SECONDS

    def idle_faces(self):
        faces = self.strip_config("idle") or DEFAULT_IDLE_FACES
        if isinstance(faces, str):
            faces = faces.split()
        faces = [f for f in faces if f in ("gifs", "dashboard")]
        return faces or list(DEFAULT_IDLE_FACES)

    # -- dashboard -----------------------------------------------------------
    def dashboard_cards(self):
        names = self.dash_cards or self.strip_config("dashboard") or metrics.DEFAULT_DASHBOARD
        if isinstance(names, str):
            names = names.split()
        return self.metrics.cards(names)

    def push_dashboard(self):
        self.push_strip_frame(renderer.cards_strip(self.dashboard_cards(), self.STRIP_FULL))

    def toggle_dashboard(self, state=None, cards=None):
        """Pin the dashboard over everything else, or let the strip go back.

        Asking for the view that is already up puts the strip back, so one
        key both opens and closes its own dashboard.
        """
        if state is None:
            state = not (self.pinned == "dashboard" and cards == self.dash_cards)
        self.pinned = "dashboard" if state else None
        self.dash_cards = cards if self.pinned else None
        self.idle_face = None
        self.idle_playing = False
        self.dash_next = self.np_next = self.gif_next = 0.0
        return self.pinned == "dashboard"

    def show_toast(self, app, summary, body="", seconds=TOAST_SECONDS):
        self.push_strip_frame(
            renderer.toast_strip(app, summary, body, self.STRIP_FULL))
        self.overlay_until = time.monotonic() + seconds
        self.dash_next = self.np_next = self.gif_next = 0.0

    # -- strip scheduling ----------------------------------------------------
    def strip_tick(self, now):
        """One writer for the strip, in priority order."""
        if self.locked or now < self.overlay_until:
            return
        if self.alert:
            if now >= self.alert_next:
                waited = now - self.alert["since"]
                self.push_strip_frame(renderer.alert_strip(
                    self.alert["app"], self.alert["summary"], self.alert["body"],
                    waited, self.STRIP_FULL, pulse=int(now) % 2 == 0))
                self.alert_next = now + 1.0
            return
        if self.pinned == "dashboard":
            if now >= self.dash_next:
                self.push_dashboard()
                self.dash_next = now + DASHBOARD_REFRESH
            return
        if self.player:
            # music is playing: show now-playing on the strip instead of GIFs
            if now >= self.np_next:
                self.push_now_playing(now)
                self.np_next = now + 1.0
            return
        if now - self.last_activity < IDLE_SECONDS:
            return
        self.idle_tick(now)

    def idle_tick(self, now):
        faces = self.idle_faces()
        if self.idle_face not in faces:
            self.idle_face = faces[0]
            self.idle_face_next = now + self.idle_face_seconds()
            self.dash_next = self.gif_next = 0.0
        elif len(faces) > 1 and now >= self.idle_face_next:
            self.idle_face = faces[(faces.index(self.idle_face) + 1) % len(faces)]
            self.idle_face_next = now + self.idle_face_seconds()
            self.dash_next = self.gif_next = 0.0
            self.idle_playing = False
        if self.idle_face == "dashboard":
            if now >= self.dash_next:
                self.push_dashboard()
                self.dash_next = now + DASHBOARD_REFRESH
            return
        segments = self.idle_segments()
        if not self.idle_playing:
            if segments:
                self.seg_loops = []
                for gif in segments:
                    path = self.asset(gif)
                    if not os.path.exists(path):
                        return
                    frames = self._loop("seg", path, lambda p: [
                        (renderer.to_jpeg(f, quality=STRIP_JPEG_QUALITY), d)
                        for f, d in renderer.gif_frames(
                            p, protocol.STRIP_LCD, protocol.ROTATION)])
                    if not frames:
                        return
                    self.seg_loops.append([frames, 0])
                self.seg_rotate_next = now + SEGMENT_ROTATE_SECONDS
            else:
                gifs = self.idle_gifs()
                path = self.asset(gifs[self.gif_index % len(gifs)])
                self.gif_index += 1
                if not os.path.exists(path):
                    return
                frames = self._loop("wide", path, self._wide_frames)
                if not frames:
                    return
                self.wide_loop = [frames, 0]
            self.idle_playing = True
            self.gif_next = 0.0
        if now >= self.gif_next:
            if segments:
                if len(self.seg_loops) > 1 and now >= self.seg_rotate_next:
                    self.seg_loops.append(self.seg_loops.pop(0))
                    self.seg_rotate_next = now + SEGMENT_ROTATE_SECONDS
                delay = self.push_segment_frames()
            else:
                delay = self.push_wide_frame()
            self.gif_next = now + delay

    def _wide_frames(self, path):
        """Pre-split a full-strip GIF: crop upright, rotate each panel."""
        w, h = protocol.STRIP_LCD
        frames = []
        for f, d in renderer.gif_frames(path, self.STRIP_FULL):
            parts = tuple(renderer.to_jpeg(
                f.crop((seg * w, 0, (seg + 1) * w, h)).rotate(protocol.ROTATION),
                quality=STRIP_JPEG_QUALITY) for seg in range(4))
            frames.append((parts, d))
        return frames

    def push_segment_frames(self):
        delay = 0.1
        for seg, loop in enumerate(self.seg_loops):
            frames, idx = loop
            data, delay = frames[idx]
            loop[1] = (idx + 1) % len(frames)
            self.dev.send_image(seg, data, strip=True)
            self.dev.flush()
        return delay

    def push_wide_frame(self):
        frames, idx = self.wide_loop
        parts, delay = frames[idx]
        self.wide_loop[1] = (idx + 1) % len(frames)
        for seg, data in enumerate(parts):
            self.dev.send_image(seg, data, strip=True)
            self.dev.flush()
        return delay

    def key_anim_tick(self, now):
        if self.locked or (self.idle_playing and self.idle_face == "gifs"):
            return
        sent = False
        for key, anim in self.key_anims.items():
            frames, idx, next_t = anim
            if now >= next_t:
                data, delay = frames[idx]
                self.dev.send_image(key, data)
                anim[1] = (idx + 1) % len(frames)
                anim[2] = now + delay
                sent = True
        if sent:
            self.dev.flush()

    # -- knob feedback overlay ----------------------------------------------
    def show_overlay(self, kind):
        if kind == "volume":
            code, out = self._run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
            tokens = out.split("Volume:")[-1].split() if code == 0 else []
            try:
                frac = min(1.0, float(tokens[0]))
            except (IndexError, ValueError):
                return
            label = "VOLUME"
        else:
            code, out = self._run(["brightnessctl", "-m"])
            fields = out.split(",") if code == 0 else []
            try:
                frac = int(fields[4].rstrip("%")) / 100.0
            except (IndexError, ValueError):
                return
            label = "BRIGHTNESS"
        frame = renderer.overlay_strip(label, frac, self.STRIP_FULL)
        self.push_strip_frame(frame)
        self.overlay_until = time.monotonic() + OVERLAY_SECONDS
        self.dash_next = self.np_next = self.gif_next = 0.0

    # -- dynamic state: mic, player, obs ------------------------------------
    def _run(self, cmd, timeout=1.0):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True)
            try:
                out, _ = proc.communicate(timeout=timeout)
                return proc.returncode, out.strip()
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return -1, ""
        except (OSError, ValueError):
            return -1, ""

    def repaint_tile(self, key, img):
        self.dev.send_image(key, renderer.to_jpeg(img))
        self.dev.flush()

    def repaint_mic(self):
        if self.mic_key is None or self.mic_muted is None:
            return
        name = "mic_muted.png" if self.mic_muted else "mic_mute.png"
        path = self.asset(f"icons/{name}")
        if os.path.exists(path):
            self.repaint_tile(self.mic_key,
                              renderer.load_icon(path, protocol.KEY_LCD, protocol.ROTATION))

    def poll_player(self):
        code, out = self._run([
            "playerctl", "--all-players", "metadata", "--format",
            "{{playerName}}\t{{status}}\t{{title}}\t{{artist}}"
            "\t{{position}}\t{{mpris:length}}\t{{mpris:artUrl}}"], timeout=1.5)
        if code != 0:
            return None
        ignored = {str(n).lower() for n in
                   ((self.strip_config("players") or {}).get("ignore") or [])}
        for line in out.splitlines():
            parts = (line.split("\t") + [""] * 7)[:7]
            name, status, title, artist, pos, length, art = parts
            # playerctl reports the bare player name ("chromium"), never the
            # instance, so ignore rules match on that; configure them per
            # profile with strip.players.ignore to keep browser tabs off
            if not name or name.split(".")[0].lower() in ignored:
                continue
            if status != "Playing":
                continue
            try:
                # playerctl reports both position and mpris:length in microseconds
                position, secs = (float(pos or 0) / 1_000_000,
                                  float(length or 0) / 1_000_000)
            except ValueError:
                continue
            if not title.strip():
                continue
            return {"title": title, "artist": artist, "position": position,
                    "length": secs, "art": art, "ts": time.monotonic()}
        return None

    def _load_art(self, url):
        if not url:
            return None
        if url == self._art_url:
            return self._art_img
        self._art_url = url
        self._art_img = None
        try:
            if url.startswith("file://"):
                path = urllib.parse.unquote(url[7:])
            elif url.startswith(("http://", "https://")):
                cache_dir = os.path.join(STATE_DIR, "ragnaros", "art")
                os.makedirs(cache_dir, exist_ok=True)
                path = os.path.join(
                    cache_dir, hashlib.sha1(url.encode()).hexdigest())
                if not os.path.exists(path):
                    urllib.request.urlretrieve(url, path)
            else:
                return None
            if path and os.path.exists(path):
                with Image.open(path) as img:
                    self._art_img = img.copy()
        except Exception as error:
            print(f"ragnaros: album art load failed: {error}", file=sys.stderr)
            self._art_img = None
        return self._art_img

    def repaint_obs(self):
        if not self.obs_keys:
            return
        st = self.obs_state or {}
        for key, action in self.obs_keys.items():
            if action == "obs:stream-toggle":
                icon = "obs_live_on.png" if st.get("streaming") else "obs_live_off.png"
                img = renderer.load_icon(self.asset(f"icons/{icon}"),
                                         protocol.KEY_LCD, protocol.ROTATION)
            elif action == "obs:record-toggle":
                icon = ("obs_pause_on.png" if st.get("paused")
                        else "obs_record_on.png" if st.get("recording")
                        else "obs_record_off.png")
                img = renderer.load_icon(self.asset(f"icons/{icon}"),
                                         protocol.KEY_LCD, protocol.ROTATION)
            elif action == "obs:pause-toggle":
                icon = "obs_pause_on.png" if st.get("paused") else "obs_pause_off.png"
                img = renderer.load_icon(self.asset(f"icons/{icon}"),
                                         protocol.KEY_LCD, protocol.ROTATION)
            elif action.startswith("obs:scene:"):
                idx = int(action.split(":", 2)[2])
                scenes = st.get("scenes") or []
                caption = (scenes[idx] if idx < len(scenes) else f"SCENE {idx + 1}")[:8].upper()
                accent = (140, 250, 160) if (scenes and idx == 0) else (170, 175, 190)
                img = renderer.state_tile(protocol.KEY_LCD[0], None, caption, accent)
                img = img.rotate(protocol.ROTATION)
            else:
                continue
            self.repaint_tile(key, img)

    def obs_action(self, action):
        if obsclient is None:
            return
        cmd = action[4:]
        try:
            if cmd == "stream-toggle":
                obsclient.command("ToggleStream")
            elif cmd == "record-toggle":
                obsclient.command("ToggleRecord")
            elif cmd == "pause-toggle":
                obsclient.command("ToggleRecordPause")
            elif cmd == "replay-save":
                obsclient.command("SaveReplayBuffer")
            elif cmd.startswith("scene:"):
                idx = int(cmd.split(":", 2)[2])
                st = self.obs_state if self.obs_state else obsclient.status()
                names = st.get("scenes") or []
                if idx < len(names):
                    obsclient.command("SetCurrentProgramScene", {"sceneName": names[idx]})
            self.obs_state = obsclient.status()
            self.obs_next_try = time.monotonic() + 10
            self.repaint_obs()
        except Exception as error:
            print(f"obs action failed ({action}): {error}", file=sys.stderr)
            self.obs_state = None
            now = time.monotonic()
            if now >= self.obs_warn_next:
                self.notify("OBS unreachable - enable its WebSocket server "
                            "and set ~/.config/ragnaros/obs.json")
                self.obs_warn_next = now + 60

    def state_tick(self, now):
        if now < self.state_next:
            return
        self.state_next = now + STATE_POLL
        if self.locked:
            return
        self.maybe_reload_profile()
        try:
            code, out = self._run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"])
            muted = code == 0 and "[MUTED]" in out
            if muted != self.mic_muted:
                self.mic_muted = muted
                self.repaint_mic()
        except Exception:
            pass
        try:
            self.player = self.poll_player()
        except Exception:
            self.player = None
        if self.obs_keys and obsclient and now >= self.obs_next_try:
            try:
                self.obs_state = obsclient.status()
            except Exception:
                self.obs_state = None
            self.obs_next_try = now + (3 if self.obs_state else 15)
            try:
                self.repaint_obs()
            except Exception:
                pass

    # -- pomodoro ------------------------------------------------------------
    def notify(self, text):
        subprocess.Popen(["notify-send", "-a", "Ragnaros", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def pomo_press(self):
        if self.pomo is None:
            self.pomo = {"phase": "focus", "ends": time.monotonic() + POMO_FOCUS,
                         "len": POMO_FOCUS}
            self.notify("Pomodoro: focus 25 min")
        elif self.pomo["phase"] == "focus":
            self.pomo = {"phase": "break", "ends": time.monotonic() + POMO_BREAK,
                         "len": POMO_BREAK}
            self.notify("Pomodoro: break 5 min")
        else:
            self.pomo = None
            self.notify("Pomodoro stopped")
        self.pomo_next = 0.0

    def repaint_pomo(self):
        if self.pomo_key is None:
            return
        if self.pomo is None:
            path = self.asset("icons/pomodoro.png")
            if not os.path.exists(path):
                return
            img = renderer.load_icon(path, protocol.KEY_LCD, protocol.ROTATION)
        else:
            left = max(0, int(self.pomo["ends"] - time.monotonic()))
            caption = f"{left // 60}:{left % 60:02d}"
            accent = (255, 120, 90) if self.pomo["phase"] == "focus" else (130, 240, 160)
            img = renderer.state_tile(protocol.KEY_LCD[0], None, caption, accent)
            img = img.rotate(protocol.ROTATION)
        self.repaint_tile(self.pomo_key, img)

    def pomo_tick(self, now):
        if self.pomo is None:
            return
        if now >= self.pomo["ends"]:
            if self.pomo["phase"] == "focus":
                self.notify("Pomodoro: focus done, take a break")
                self.pomo = {"phase": "break", "ends": now + POMO_BREAK, "len": POMO_BREAK}
            else:
                self.notify("Pomodoro: break over, back to focus")
                self.pomo = {"phase": "focus", "ends": now + POMO_FOCUS, "len": POMO_FOCUS}
            self.pomo_next = 0.0
        if now >= self.pomo_next:
            self.repaint_pomo()
            self.pomo_next = now + 1.0

    # -- now playing strip ----------------------------------------------------
    def push_now_playing(self, now):
        player = self.player
        elapsed = player["position"] + (now - player["ts"])
        art = self._load_art(player.get("art"))
        frame = renderer.now_playing_strip(
            player["title"], player["artist"], min(elapsed, player["length"] or elapsed),
            player["length"], self.STRIP_FULL, art)
        self.push_strip_frame(frame)

    # -- desktop events ------------------------------------------------------
    def set_locked(self, locked):
        if locked == self.locked:
            return
        self.locked = locked
        print(f"ragnaros: session {'locked' if locked else 'unlocked'}", file=sys.stderr)
        try:
            if locked:
                self.dev.set_brightness(0)
            else:
                self.dev.set_brightness(self.brightness)
                self.paint_keys()
                self.last_activity = time.monotonic()
                self.dash_next = self.np_next = self.gif_next = 0.0
        except RuntimeError as error:
            print(f"ragnaros: brightness change failed: {error}", file=sys.stderr)

    def on_notification(self, data):
        config = self.profile.get("notifications")
        config = {} if config is None else config
        if config.get("enabled") is False:
            return
        app = (data.get("app") or "").strip()
        ignore = {str(a).lower() for a in (config.get("ignore") or [])}
        ignore.add("ragnaros")  # our own notify-send must not bounce back
        if app.lower() in ignore:
            return
        summary, body = data.get("summary") or "", data.get("body") or ""
        signature = f"{app}|{summary}|{body}"
        now = time.monotonic()
        # the shell re-dispatches every Notify call, so the bus shows it twice
        if signature == self._last_toast[0] and now - self._last_toast[1] < 2.0:
            return
        self._last_toast = (signature, now)
        self.show_toast(app, summary, body,
                        float(config.get("seconds", TOAST_SECONDS)))

    def desktop_tick(self):
        if not self.dbus:
            return
        for kind, data in self.dbus.drain():
            if kind == "lock":
                self.set_locked(bool(data))
            elif kind == "notify":
                try:
                    self.on_notification(data)
                except Exception as error:
                    print(f"ragnaros: toast failed: {error}", file=sys.stderr)

    # -- control socket ------------------------------------------------------
    def control_tick(self):
        if self.control:
            self.control.serve(self.handle_control)

    def strip_state(self):
        if self.locked:
            return "off"
        if time.monotonic() < self.overlay_until:
            return "notice"  # a toast or a knob overlay, on its way out
        if self.alert:
            return "alert"
        if self.pinned:
            return self.pinned
        if self.player:
            return "now-playing"
        return self.idle_face or "keys"

    def handle_control(self, argv):
        if not argv:
            return {"ok": False, "error": "empty command"}
        command, args = argv[0], argv[1:]
        if command in ("status", "state"):
            return {"ok": True, "profile": self.profile.get("_name"),
                    "profiles": available_profiles(),
                    "layer": self.layer or "base", "layers": sorted(self.layers()),
                    "strip": self.strip_state(), "brightness": self.brightness,
                    "locked": self.locked, "dashboard": self.pinned == "dashboard",
                    "player": self.player and {k: self.player[k]
                                               for k in ("title", "artist", "length")},
                    "alert": self.alert and self.alert["summary"],
                    "watchers": len(self.control.subscribers) if self.control else 0,
                    "pomodoro": self.pomo and self.pomo["phase"],
                    "obs": self.obs_state}
        if command in ("profile", "profiles"):
            if not args or args[0] == "list":
                return {"ok": True, "profiles": available_profiles(),
                        "current": self.profile.get("_name")}
            target = args[0]
            if target in ("next", "prev"):
                self.cycle_profile(1 if target == "next" else -1)
            elif os.path.exists(profile_path(target)):
                self.switch_profile(target)
            else:
                return {"ok": False, "error": f"no such profile: {target}"}
            return {"ok": True, "profile": self.profile.get("_name")}
        if command == "layer":
            if not args or args[0] == "list":
                return {"ok": True, "layers": sorted(self.layers()),
                        "current": self.layer or "base"}
            if not self.set_layer(args[0]):
                return {"ok": False, "error": f"no such layer: {args[0]}"}
            return {"ok": True, "layer": self.layer or "base"}
        if command == "brightness":
            if args:
                try:
                    self.brightness = max(0, min(100, int(args[0])))
                except ValueError:
                    return {"ok": False, "error": "brightness takes 0-100"}
                if not self.locked:
                    self.dev.set_brightness(self.brightness)
            return {"ok": True, "brightness": self.brightness}
        if command == "dashboard":
            state = {"on": True, "off": False}.get(args[0] if args else "toggle")
            cards = [c for a in args[1:] if not a.startswith("-")
                     for c in a.replace(",", " ").split()] or None
            if state is None and args and args[0] not in ("toggle",):
                cards = [c for a in args for c in a.replace(",", " ").split()]
                state = True
            return {"ok": True, "dashboard": self.toggle_dashboard(state, cards),
                    "cards": self.dash_cards or self.strip_config("dashboard")
                    or list(metrics.DEFAULT_DASHBOARD)}
        if command == "watch":
            return {"ok": True, "watching": True, "grab": "--grab" in args,
                    "profile": self.profile.get("_name"),
                    "_stream": {"grab": "--grab" in args}}
        if command == "alert":
            if not args or args[0] in ("--clear", "clear", "off"):
                return {"ok": True, "alert": None, "cleared": self.clear_alert()}
            text = [a for a in args if not a.startswith("--")]
            flags = dict(a[2:].split("=", 1) for a in args
                         if a.startswith("--") and "=" in a)
            self.set_alert(flags.get("app", "aviso"), text[0], " ".join(text[1:]))
            return {"ok": True, "alert": self.alert["summary"]}
        if command == "toast":
            text = [a for a in args if not a.startswith("--")]
            flags = dict(a[2:].split("=", 1) for a in args
                         if a.startswith("--") and "=" in a)
            if not text:
                return {"ok": False, "error": "toast needs a summary"}
            self.show_toast(flags.get("app", "ragnaros"), text[0],
                            " ".join(text[1:]), float(flags.get("seconds", TOAST_SECONDS)))
            return {"ok": True}
        if command == "key":
            try:
                spec = self.active_keys().get(str(int(args[0]))) or {}
            except (IndexError, ValueError):
                return {"ok": False, "error": "key takes an index 0-9"}
            if "profile" in spec:
                self.switch_profile(spec["profile"])
            else:
                self.run_deck_action(spec.get("action"))
            return {"ok": True, "action": spec.get("action") or spec.get("profile")}
        if command == "reload":
            self.profile = load_profile(self.profile["_name"])
            self._icon_cache.clear()
            self._loop_cache.clear()
            self.apply_profile()
            return {"ok": True, "profile": self.profile.get("_name")}
        if command in ("sleep", "wake"):
            self.set_locked(command == "sleep")
            return {"ok": True, "locked": self.locked}
        return {"ok": False, "error": f"unknown command: {command}"}

    def reconnect(self):
        print("ragnaros: device lost, waiting for reattach", file=sys.stderr)
        try:
            self.dev.close()
        except Exception:
            pass
        self._wait_for_device()
        self.apply_profile()
        self.mic_muted = None  # force state repaints after reattach
        self.obs_state = None

    def run(self):
        try:
            self.control = control.Control()
            print(f"ragnaros: control socket {self.control.path}", file=sys.stderr)
        except OSError as error:
            print(f"ragnaros: control socket unavailable: {error}", file=sys.stderr)
        self.dbus = dbuswatch.DBusWatch()
        try:
            self.apply_profile()
            while True:
                try:
                    # the device watchdog drops the strip to its default
                    # logo without a periodic CONNECT (official app: 10s timer)
                    now = time.monotonic()
                    if now >= self.keepalive_next and not os.environ.get("RAGNAROS_NO_KEEPALIVE"):
                        self.dev.keep_alive()
                        self.keepalive_next = now + 8.0
                    event = self.dev.poll(50)
                    if event:
                        self.handle_event(event)
                    now = time.monotonic()
                    self.desktop_tick()
                    self.control_tick()
                    self.state_tick(now)
                    self.strip_tick(now)
                    self.pomo_tick(now)
                    self.key_anim_tick(now)
                except RuntimeError as error:
                    print(f"ragnaros: {error}", file=sys.stderr)
                    self.reconnect()
        finally:
            if self.control:
                self.control.close()
            if self.dbus:
                self.dbus.close()
            self.dev.close()


if __name__ == "__main__":
    Deck().run()
