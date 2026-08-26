#!/usr/bin/env python3
import os
import shlex
import subprocess
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import protocol
import renderer

CONFIG_DIR = os.environ.get("RAGNAROS_CONFIG", os.path.expanduser("~/.config/ragnaros"))
IDLE_SECONDS = float(os.environ.get("RAGNAROS_IDLE_SECONDS", "10"))


def load_profile(name):
    path = os.path.join(CONFIG_DIR, "profiles", f"{name}.yaml")
    with open(path) as f:
        profile = yaml.safe_load(f)
    profile["_name"] = name
    return profile


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
        self.profile = load_profile("streaming")
        self.last_activity = time.monotonic()
        self.idle_playing = False
        self.gif_iter = None
        self.gif_next = 0.0
        self.gif_index = 0
        self.key_anims = {}
        self.knob_last = {}

    def asset(self, rel):
        return os.path.join(CONFIG_DIR, "assets", rel)

    def apply_profile(self):
        self.key_anims = {}
        for key, spec in (self.profile.get("keys") or {}).items():
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

    def switch_profile(self, name):
        self.profile = load_profile(name)
        self.apply_profile()

    def handle_event(self, event):
        self.last_activity = time.monotonic()
        self.idle_playing = False
        kind, idx, value = event
        if kind == "key" and value:
            spec = (self.profile.get("keys") or {}).get(str(idx)) or {}
            if "profile" in spec:
                self.switch_profile(spec["profile"])
            else:
                run_action(spec.get("action"))
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
                run_action(rotate.get("cw" if value > 0 else "ccw"))
        elif kind == "knob_press":
            spec = (self.profile.get("knobs") or {}).get(str(idx)) or {}
            run_action(spec.get("press"))

    STRIP_FULL = (protocol.STRIP_LCD[0] * 4, protocol.STRIP_LCD[1])

    def push_strip_frame(self, frame):
        w, h = protocol.STRIP_LCD
        for seg in range(4):
            part = frame.crop((seg * w, 0, (seg + 1) * w, h))
            self.dev.send_image(seg, renderer.to_jpeg(part), strip=True)
            self.dev.flush()  # strip segments only display when flushed per image

    def idle_gifs(self):
        gifs = (self.profile.get("strip") or {}).get("gif", "gifs/nanami.gif")
        return [gifs] if isinstance(gifs, str) else gifs

    def idle_segments(self):
        segs = (self.profile.get("strip") or {}).get("segments")
        return segs[:4] if segs else None

    def idle_tick(self, now):
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
        for seg, loop in enumerate(self.seg_loops):
            frames, idx = loop
            frame, delay = frames[idx]
            loop[1] = (idx + 1) % len(frames)
            self.dev.send_image(seg, renderer.to_jpeg(frame), strip=True)
            self.dev.flush()  # strip segments only display when flushed per image
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

    def run(self):
        try:
            self.apply_profile()
            while True:
                event = self.dev.poll(50)
                if event:
                    self.handle_event(event)
                now = time.monotonic()
                self.idle_tick(now)
                self.key_anim_tick(now)
        finally:
            self.dev.close()


if __name__ == "__main__":
    Deck().run()
