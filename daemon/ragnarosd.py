#!/usr/bin/env python3
import os
import selectors
import shlex
import subprocess
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import protocol
import renderer

CONFIG_DIR = os.environ.get("RAGNAROS_CONFIG", os.path.expanduser("~/.config/ragnaros"))
IDLE_SECONDS = 60


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
    subprocess.Popen(
        shlex.split(action),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class Deck:
    def __init__(self):
        nodes = protocol.find_hidraw_nodes()
        if not nodes:
            sys.exit("Ragnaros not found (0200:3001) - check udev rule and hidraw permissions")
        self.dev = protocol.RagnarosProtocol(nodes[0])
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.dev.fd, selectors.EVENT_READ)
        self.profile = load_profile("streaming")
        self.last_activity = time.monotonic()
        self.idle_playing = False
        self.gif_iter = None
        self.gif_next = 0.0

    def asset(self, rel):
        return os.path.join(CONFIG_DIR, "assets", rel)

    def apply_profile(self):
        for key, spec in (self.profile.get("keys") or {}).items():
            icon = spec.get("icon")
            if icon and os.path.exists(self.asset(icon)):
                img = renderer.load_icon(self.asset(icon), protocol.KEY_LCD)
                self.try_send(self.dev.set_key_image, int(key), renderer.to_bytes(img))

    def try_send(self, fn, *args):
        try:
            fn(*args)
        except NotImplementedError as e:
            print(f"protocol stub: {e}", file=sys.stderr)

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
            spec = (self.profile.get("knobs") or {}).get(str(idx)) or {}
            rotate = spec.get("rotate")
            if isinstance(rotate, dict):
                run_action(rotate.get("cw" if value > 0 else "ccw"))
        elif kind == "knob_press":
            spec = (self.profile.get("knobs") or {}).get(str(idx)) or {}
            run_action(spec.get("press"))

    def idle_tick(self, now):
        if now - self.last_activity < IDLE_SECONDS:
            return
        gif = (self.profile.get("strip") or {}).get("gif", "gifs/jjk.gif")
        path = self.asset(gif)
        if not os.path.exists(path):
            return
        if not self.idle_playing:
            self.gif_iter = renderer.gif_frames(path, protocol.STRIP_LCD)
            self.idle_playing = True
            self.gif_next = 0.0
        if now >= self.gif_next:
            try:
                frame, delay = next(self.gif_iter)
            except StopIteration:
                self.gif_iter = renderer.gif_frames(path, protocol.STRIP_LCD)
                frame, delay = next(self.gif_iter)
            self.try_send(self.dev.set_strip_image, renderer.to_bytes(frame))
            self.gif_next = now + delay

    def run(self):
        self.apply_profile()
        while True:
            for key, _ in self.sel.select(timeout=0.05):
                try:
                    event = self.dev.poll()
                except NotImplementedError as e:
                    sys.exit(f"protocol stub: {e}")
                if event:
                    self.handle_event(event)
            self.idle_tick(time.monotonic())


if __name__ == "__main__":
    Deck().run()
