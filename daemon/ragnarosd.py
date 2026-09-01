#!/usr/bin/env python3
import json
import os
import shlex
import subprocess
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

POMO_FOCUS = 25 * 60
POMO_BREAK = 5 * 60


def load_profile(name):
    path = os.path.join(CONFIG_DIR, "profiles", f"{name}.yaml")
    with open(path) as f:
        profile = yaml.safe_load(f)
    profile["_name"] = name
    return profile


def saved_profile_name():
    try:
        with open(os.path.join(STATE_DIR, "ragnaros", "profile")) as f:
            name = f.read().strip()
        if name and os.path.exists(os.path.join(CONFIG_DIR, "profiles", f"{name}.yaml")):
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
        try:
            self.dev = protocol.Ragnaros()
        except RuntimeError as error:
            sys.exit(f"Ragnaros unavailable: {error}")
        self.profile = load_profile(saved_profile_name())
        self.last_activity = time.monotonic()
        self.idle_playing = False
        self.gif_iter = None
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

    def asset(self, rel):
        return os.path.join(CONFIG_DIR, "assets", rel)

    def apply_profile(self):
        self.key_anims = {}
        keys = self.profile.get("keys") or {}
        for key, spec in keys.items():
            icon = spec.get("icon")
            if not icon or not os.path.exists(self.asset(icon)):
                continue
            path = self.asset(icon)
            if path.endswith(".gif"):
                frames = list(renderer.gif_frames(path, protocol.KEY_LCD, protocol.ROTATION))
                if frames:
                    self.key_anims[int(key)] = [frames, 0, 0.0]
            else:
                img = renderer.load_icon(path, protocol.KEY_LCD, protocol.ROTATION)
                self.dev.send_image(int(key), renderer.to_jpeg(img))
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
        self.idle_playing = False
        self.last_activity = time.monotonic() - IDLE_SECONDS
        self.idle_tick(time.monotonic())

    def switch_profile(self, name):
        self.profile = load_profile(name)
        save_profile_name(name)
        self.apply_profile()

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

    def handle_event(self, event):
        self.last_activity = time.monotonic()
        self.idle_playing = False
        kind, idx, value = event
        if kind == "key" and value:
            spec = (self.profile.get("keys") or {}).get(str(idx)) or {}
            if "profile" in spec:
                self.log_usage(event, f"switch:{spec['profile']}")
                self.switch_profile(spec["profile"])
                return
            action = spec.get("action")
            self.log_usage(event, action)
            if action == "pomodoro":
                self.pomo_press()
            elif isinstance(action, str) and action.startswith("obs:"):
                self.obs_action(action)
            else:
                run_action(action)
        elif kind == "knob":
            # the device bursts several reports per detent; act on one per 120ms
            now = time.monotonic()
            token = (idx, value > 0)
            if now - self.knob_last.get(token, 0) < 0.12:
                return
            self.knob_last[token] = now
            spec = (self.profile.get("knobs") or {}).get(str(idx)) or {}
            rotate = spec.get("rotate")
            if isinstance(rotate, dict):
                action = rotate.get("cw" if value > 0 else "ccw")
                self.log_usage(event, action)
                run_action(action)
        elif kind == "knob_press":
            spec = (self.profile.get("knobs") or {}).get(str(idx)) or {}
            self.log_usage(event, spec.get("press"))
            run_action(spec.get("press"))

    STRIP_FULL = (protocol.STRIP_LCD[0] * 4, protocol.STRIP_LCD[1])

    def push_strip_frame(self, frame):
        w, h = protocol.STRIP_LCD
        parts = []
        for seg in range(4):
            parts.append(renderer.to_jpeg(frame.crop((seg * w, 0, (seg + 1) * w, h))))
        for _ in range(2):
            for seg, data in enumerate(parts):
                self.dev.send_image(seg, data, strip=True)
                self.dev.flush()

    def idle_gifs(self):
        gifs = (self.profile.get("strip") or {}).get("gif", "gifs/nanami.gif")
        return [gifs] if isinstance(gifs, str) else gifs

    def idle_segments(self):
        segs = (self.profile.get("strip") or {}).get("segments")
        return segs[:4] if segs else None

    def idle_tick(self, now):
        if self.player:
            # music is playing: show now-playing on the strip instead of GIFs
            if now >= self.np_next:
                self.push_now_playing(now)
                self.np_next = now + 1.0
            return
        if now - self.last_activity < IDLE_SECONDS:
            return
        segments = self.idle_segments()
        if not self.idle_playing:
            if segments:
                self.seg_loops = []
                for gif in segments:
                    path = self.asset(gif)
                    if not os.path.exists(path):
                        return
                    frames = list(renderer.gif_frames(path, protocol.STRIP_LCD, protocol.ROTATION))
                    if not frames:
                        return
                    self.seg_loops.append([frames, 0])
            else:
                gifs = self.idle_gifs()
                path = self.asset(gifs[self.gif_index % len(gifs)])
                self.gif_index += 1
                if not os.path.exists(path):
                    return
                self.wide_loop = [list(renderer.gif_frames(path, self.STRIP_FULL, protocol.ROTATION)), 0]
                if not self.wide_loop[0]:
                    return
            self.idle_playing = True
            self.gif_next = 0.0
        if now >= self.gif_next:
            if segments:
                delay = self.push_segment_frames()
            else:
                delay = self.push_wide_frame()
            self.gif_next = now + delay

    def push_segment_frames(self):
        delay = 0.1
        jpeg = [None] * len(self.seg_loops)
        for seg, loop in enumerate(self.seg_loops):
            frames, idx = loop
            frame, delay = frames[idx]
            jpeg[seg] = renderer.to_jpeg(frame)
            loop[1] = (idx + 1) % len(frames)
        # write all segments, twice each, with a single flush at the end of each
        # repetition so the device never has a gap to fall back to its
        # default Reddragon logo on the strip LCD.
        for _ in range(2):
            for seg, data in enumerate(jpeg):
                self.dev.send_image(seg, data, strip=True)
                self.dev.flush()
        return delay

    def push_wide_frame(self):
        frames, idx = self.wide_loop
        frame, delay = frames[idx]
        self.wide_loop[1] = (idx + 1) % len(frames)
        self.push_strip_frame(frame)
        return delay

    def key_anim_tick(self, now):
        if self.idle_playing:
            return
        sent = False
        for key, anim in self.key_anims.items():
            frames, idx, next_t = anim
            if now >= next_t:
                frame, delay = frames[idx]
                self.dev.send_image(key, renderer.to_jpeg(frame))
                anim[1] = (idx + 1) % len(frames)
                anim[2] = now + delay
                sent = True
        if sent:
            self.dev.flush()

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
        try:
            # ignore browser-backed "playing" tabs (autoplay, unmuted ads)
            # that aren't real music sessions
            code, out = self._run(["playerctl", "-l"], timeout=1.0)
            if code != 0:
                return None
            players = [p for p in out.splitlines()
                       if not (p.startswith(("chromium.", "brave.", "firefox.instance"))
                              or ".instance" in p)]
            if not players:
                return None
            player = players[0]
            code, out = self._run(["playerctl", "-p", player, "status"])
            if code != 0 or out.strip() != "Playing":
                return None
            code, out = self._run([
                "playerctl", "-p", player, "metadata", "--format",
                "{{title}}\t{{artist}}\t{{position}}\t{{mpris:length}}"])
            if code != 0:
                return None
            title, artist, pos, length = (out.split("\t") + ["", "", "0", "0"])[:4]
            try:
                position, secs = float(pos), float(length) / 1_000_000
            except ValueError:
                return None
            if not title.strip():
                return None
            return {"title": title, "artist": artist,
                    "position": position, "length": secs, "ts": time.monotonic()}
        except subprocess.SubprocessError:
            return None

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
        frame = renderer.now_playing_strip(
            player["title"], player["artist"], min(elapsed, player["length"] or elapsed),
            player["length"], self.STRIP_FULL)
        self.push_strip_frame(frame.rotate(protocol.ROTATION))

    def reconnect(self):
        print("ragnaros: device lost, waiting for reattach", file=sys.stderr)
        try:
            self.dev.close()
        except Exception:
            pass
        while True:
            try:
                self.dev = protocol.Ragnaros()
                break
            except RuntimeError:
                time.sleep(1)
        self.dev.initialize()
        self.apply_profile()
        self.mic_muted = None  # force state repaints after reattach
        self.obs_state = None

    def run(self):
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
                    self.state_tick(now)
                    self.idle_tick(now)
                    self.pomo_tick(now)
                    self.key_anim_tick(now)
                except RuntimeError as error:
                    print(f"ragnaros: {error}", file=sys.stderr)
                    self.reconnect()
        finally:
            self.dev.close()


if __name__ == "__main__":
    Deck().run()
