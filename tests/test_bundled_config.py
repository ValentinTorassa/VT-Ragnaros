"""The bundled profiles and assets, checked the way the daemon uses them.

No deck needed: every profile is parsed strictly and checked against the
fields ragnarosd.py actually reads, every image under assets/ is decoded with
the geometry its panel expects, and each profile is painted and idled once
against a recording fake device.
"""
import glob
import io
import os
import shlex
import time
from types import SimpleNamespace

import pytest
import yaml
from PIL import Image, ImageSequence

from ragnaros import daemon as ragnarosd
from ragnaros import fetch_gifs, metrics, paths, protocol, strip_gif

ASSETS = paths.bundled("assets")
PROFILE_NAMES = ragnarosd.available_profiles()
PANELS = ragnarosd.Deck.STRIP_FULL[0] // protocol.STRIP_LCD[0]
# every frame stays pre-encoded in memory for the life of the daemon
MAX_FRAMES = 500

# the fields ragnarosd.py reads; anything else is a typo it would ignore
TOP_LEVEL = {"name", "strip", "keys", "knobs", "layers", "notifications"}
KEY_FIELDS = {"icon", "action", "profile", "layer", "layer_toggle"}
KEY_HANDLERS = ("action", "profile", "layer", "layer_toggle")
KNOB_FIELDS = {"rotate", "press"}
LAYER_FIELDS = {"keys", "knobs"}
STRIP_FIELDS = {"segments", "gif", "pinned", "idle", "idle_seconds", "dashboard",
                "players", "touch", "swipe"}
NOTIFICATION_FIELDS = {"enabled", "seconds", "ignore"}


# -- strict YAML ---------------------------------------------------------------
class StrictLoader(yaml.SafeLoader):
    """safe_load, except that a repeated key fails instead of silently winning."""


def _unique_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark)
        seen.add(key)
    return loader.construct_mapping(node, deep)


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def read_profile(name):
    with open(ragnarosd.profile_path(name)) as f:
        return yaml.load(f, Loader=StrictLoader)


# -- schema --------------------------------------------------------------------
def is_asset(rel):
    return isinstance(rel, str) and os.path.isfile(os.path.join(ASSETS, rel))


def index_issues(where, mapping, count):
    """Events look indices up as str(index): 0 and "03" would never fire."""
    for idx in mapping:
        if not (isinstance(idx, str) and idx.isdigit() and idx == str(int(idx))):
            yield f"{where}.{idx!r}: index must be a quoted number like \"3\""
        elif not 0 <= int(idx) < count:
            yield f"{where}.{idx}: index outside 0-{count - 1}"


def is_deck_verb(action):
    """Mirrors the dispatch order of Deck.run_deck_action."""
    return (action == "pomodoro" or action.split(":")[0] == "dashboard"
            or action.startswith(("obs:", "profile:", "layer:")))


def shell_issues(where, cmd):
    if not isinstance(cmd, str) or not cmd.strip():
        yield f"{where}: empty or non-string command {cmd!r}"
        return
    try:
        shlex.split(cmd)
    except ValueError as error:
        yield f"{where}: {cmd!r} does not parse as a shell command ({error})"


def action_issues(where, action, profile, shell_only=False):
    """An action run by run_deck_action, or by run_action when shell_only."""
    if isinstance(action, list):
        for i, cmd in enumerate(action):
            if isinstance(cmd, str) and is_deck_verb(cmd):
                yield f"{where}[{i}]: deck verb {cmd!r} only works on its own, not in a list"
            else:
                yield from shell_issues(f"{where}[{i}]", cmd)
        return
    if not isinstance(action, str) or not action.strip():
        yield f"{where}: empty or non-string action {action!r}"
        return
    if not is_deck_verb(action):
        yield from shell_issues(where, action)
        return
    if shell_only:
        yield f"{where}: deck verb {action!r} would be run as a shell command here"
    elif action.split(":")[0] == "dashboard":
        cards = action.partition(":")[2].replace(",", " ").split()
        yield from card_issues(where, cards)
    elif action.startswith("profile:"):
        if action.split(":", 1)[1] not in PROFILE_NAMES:
            yield f"{where}: {action!r} names no profile in profiles/"
    elif action.startswith("layer:"):
        target = action.split(":", 1)[1]
        if target and target not in (profile.get("layers") or {}):
            yield f"{where}: {action!r} names no layer of this profile"
    # obs:* verbs are driven through the real dispatcher in test_obs_keys_reach_obs


def card_issues(where, cards):
    unknown = [c for c in cards if c not in metrics.PROVIDERS]
    if unknown:
        yield f"{where}: unknown dashboard cards {unknown}; known: {list(metrics.PROVIDERS)}"
    if len(cards) > PANELS:
        yield f"{where}: {len(cards)} dashboard cards, the strip shows {PANELS}"


def key_issues(where, keys, profile):
    if not isinstance(keys, dict):
        yield f"{where}: not a mapping"
        return
    yield from index_issues(where, keys, protocol.KEY_COUNT)
    layers = profile.get("layers") or {}
    for idx, spec in keys.items():
        w = f"{where}.{idx}"
        if not isinstance(spec, dict):
            yield f"{w}: not a mapping"
            continue
        if set(spec) - KEY_FIELDS:
            yield f"{w}: unknown fields {sorted(set(spec) - KEY_FIELDS)}"
        handlers = [h for h in KEY_HANDLERS if h in spec]
        if len(handlers) != 1:
            yield f"{w}: needs exactly one of {'/'.join(KEY_HANDLERS)}, has {handlers or 'none'}"
        if "profile" in spec and spec["profile"] not in PROFILE_NAMES:
            yield f"{w}: profile {spec['profile']!r} is not in profiles/"
        for field in ("layer", "layer_toggle"):
            if field in spec and spec[field] not in layers:
                yield f"{w}: {field} {spec[field]!r} is not a layer of this profile"
        if "action" in spec:
            yield from action_issues(f"{w}.action", spec["action"], profile)
        if "icon" in spec and not is_asset(spec["icon"]):
            yield f"{w}: missing asset {spec['icon']!r}"


def knob_issues(where, knobs, profile):
    if not isinstance(knobs, dict):
        yield f"{where}: not a mapping"
        return
    yield from index_issues(where, knobs, protocol.KNOB_COUNT)
    for idx, spec in knobs.items():
        w = f"{where}.{idx}"
        if not isinstance(spec, dict):
            yield f"{w}: not a mapping"
            continue
        if set(spec) - KNOB_FIELDS:
            yield f"{w}: unknown fields {sorted(set(spec) - KNOB_FIELDS)}"
        rotate = spec.get("rotate")
        if rotate is not None:
            if not isinstance(rotate, dict) or set(rotate) - {"cw", "ccw"}:
                yield f"{w}.rotate: must be a mapping of cw/ccw"
            else:
                # a turn goes straight to run_action: deck verbs are not understood
                for direction, action in rotate.items():
                    yield from action_issues(f"{w}.rotate.{direction}", action, profile,
                                             shell_only=True)
        if "press" in spec:
            yield from action_issues(f"{w}.press", spec["press"], profile)


def strip_issues(strip, profile):
    if not isinstance(strip, dict):
        yield "strip: not a mapping"
        return
    if set(strip) - STRIP_FIELDS:
        yield f"strip: unknown fields {sorted(set(strip) - STRIP_FIELDS)}"
    segments = strip.get("segments")
    if segments is not None:
        if not isinstance(segments, list) or not segments:
            yield "strip.segments: must be a non-empty list"
        else:
            if len(segments) > PANELS:
                yield f"strip.segments: {len(segments)} GIFs for {PANELS} panels, the rest are dropped"
            for gif in segments:
                if not is_asset(gif):
                    yield f"strip.segments: missing asset {gif!r}"
    if "gif" in strip:
        gifs = [strip["gif"]] if isinstance(strip["gif"], str) else strip["gif"]
        if not isinstance(gifs, list) or not gifs:
            yield "strip.gif: must be a path or a non-empty list of paths"
        else:
            for gif in gifs:
                if not is_asset(gif):
                    yield f"strip.gif: missing asset {gif!r}"
    if strip.get("pinned") not in (None, "dashboard"):
        yield f"strip.pinned: {strip['pinned']!r} is ignored, only 'dashboard' pins"
    if "idle" in strip:
        faces = strip["idle"].split() if isinstance(strip["idle"], str) else strip["idle"]
        if not isinstance(faces, list) or not set(faces) <= set(ragnarosd.DEFAULT_IDLE_FACES):
            yield f"strip.idle: {strip['idle']!r}; faces are {list(ragnarosd.DEFAULT_IDLE_FACES)}"
    if "idle_seconds" in strip:
        seconds = strip["idle_seconds"]
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 3:
            yield f"strip.idle_seconds: {seconds!r}; a number of at least 3"
    if "dashboard" in strip:
        cards = strip["dashboard"]
        cards = cards.split() if isinstance(cards, str) else cards
        if not isinstance(cards, list):
            yield "strip.dashboard: must be a list of card names"
        else:
            yield from card_issues("strip.dashboard", cards)
    if "players" in strip:
        players = strip["players"]
        if not isinstance(players, dict) or set(players) - {"ignore"} or \
                not isinstance(players.get("ignore", []), list):
            yield "strip.players: expected {ignore: [player names]}"
    touch = strip.get("touch") or {}
    yield from index_issues("strip.touch", touch, PANELS)
    for idx, action in touch.items():
        yield from action_issues(f"strip.touch.{idx}", action, profile)
    swipe = strip.get("swipe") or {}
    if set(swipe) - {"left", "right"}:
        yield f"strip.swipe: unknown directions {sorted(set(swipe) - {'left', 'right'})}"
    for direction, action in swipe.items():
        yield from action_issues(f"strip.swipe.{direction}", action, profile)


def profile_issues(name, profile):
    if not isinstance(profile, dict):
        return [f"{name}: not a mapping"]
    issues = []
    if set(profile) - TOP_LEVEL:
        issues.append(f"unknown top-level fields {sorted(set(profile) - TOP_LEVEL)}")
    if profile.get("name") != name:
        issues.append(f"name: {profile.get('name')!r} differs from the file name {name!r}")
    issues += key_issues("keys", profile.get("keys") or {}, profile)
    issues += knob_issues("knobs", profile.get("knobs") or {}, profile)
    layers = profile.get("layers") or {}
    for layer, spec in layers.items():
        if not isinstance(spec, dict) or set(spec) - LAYER_FIELDS:
            issues.append(f"layers.{layer}: expected a mapping with keys/knobs")
            continue
        issues += key_issues(f"layers.{layer}.keys", spec.get("keys") or {}, profile)
        issues += knob_issues(f"layers.{layer}.knobs", spec.get("knobs") or {}, profile)
    issues += strip_issues(profile.get("strip") or {}, profile)
    notifications = profile.get("notifications")
    if notifications is not None:
        if not isinstance(notifications, dict) or set(notifications) - NOTIFICATION_FIELDS:
            issues.append(f"notifications: fields are {sorted(NOTIFICATION_FIELDS)}")
        else:
            if not isinstance(notifications.get("enabled", True), bool):
                issues.append("notifications.enabled: must be true or false")
            seconds = notifications.get("seconds", 1)
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0:
                issues.append(f"notifications.seconds: {seconds!r}; a positive number")
            if not isinstance(notifications.get("ignore", []), list):
                issues.append("notifications.ignore: must be a list of app names")
    return [f"{name}: {i}" for i in issues]


def test_there_are_profiles_to_check():
    assert "streaming" in PROFILE_NAMES  # the daemon's fallback profile


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_profile_matches_what_the_daemon_reads(name):
    profile = read_profile(name)
    assert profile_issues(name, profile) == []


def test_the_schema_check_catches_mistakes():
    profile = {
        "name": "other",
        "colour": "red",
        "keys": {0: {"icon": "icons/lock.png", "action": "true"},
                 "4": {"profile": "ghost"},
                 "5": {"layer_toggle": "nope", "action": "true"},
                 "6": {"action": "echo 'unterminated"}},
        "knobs": {"4": {"press": "true"},
                  "1": {"rotate": {"cw": "layer:media"}, "press": "dashboard:cpu,fps"}},
        "strip": {"segments": ["gifs/segments/mine.gif"] * 5, "pinned": "gifs",
                  "touch": {"4": "true"}, "swipe": {"up": "true"}},
    }
    issues = "\n".join(profile_issues("test", profile))
    for expected in ("unknown top-level fields ['colour']",
                     "differs from the file name",
                     "keys.0: index must be a quoted number",
                     "profile 'ghost' is not in profiles/",
                     "keys.5: needs exactly one of",
                     "layer_toggle 'nope' is not a layer",
                     "does not parse as a shell command",
                     "knobs.4: index outside 0-3",
                     "deck verb 'layer:media' would be run as a shell command",
                     "unknown dashboard cards ['fps']",
                     "5 GIFs for 4 panels",
                     "strip.pinned: 'gifs' is ignored",
                     "strip.touch.4: index outside 0-3",
                     "unknown directions ['up']"):
        assert expected in issues


def test_duplicate_yaml_keys_are_refused():
    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key '3'"):
        yaml.load('keys:\n  "3": {action: a}\n  "3": {action: b}\n', Loader=StrictLoader)


# -- assets --------------------------------------------------------------------
# assets/gifs is never shipped (a checkout may hold a local link to a
# downloaded GIF theme there), so only the bundled trees are checked
IMAGES = sorted(rel for rel in (os.path.relpath(p, ASSETS) for p in glob.glob(
    os.path.join(ASSETS, "**", "*"), recursive=True))
    if rel.lower().endswith((".png", ".gif", ".jpg", ".jpeg"))
    and rel.split(os.sep)[0] != "gifs")


def decode(path):
    """Decode every frame the way renderer.gif_frames will."""
    frames = 0
    with Image.open(path) as img:
        fmt, size = img.format, img.size
        for frame in ImageSequence.Iterator(img):
            frame.convert("RGB")
            frames += 1
    return fmt, size, frames


def test_no_third_party_gifs_are_bundled():
    tomllib = pytest.importorskip("tomllib")
    with open(os.path.join(os.path.dirname(paths.PACKAGE_DIR), "pyproject.toml"), "rb") as f:
        build = tomllib.load(f)["tool"]["hatch"]["build"]["targets"]
    shipped = list(build["wheel"]["force-include"]) + build["sdist"]["include"]
    assert not [src for src in shipped if "gifs" in src], shipped
    assert all(os.path.dirname(rel) in ("icons", "strip") for rel in IMAGES), IMAGES


@pytest.mark.parametrize("rel", IMAGES)
def test_image_asset_decodes_with_sane_geometry(rel):
    fmt, (w, h), frames = decode(os.path.join(ASSETS, rel))
    assert 1 <= frames <= MAX_FRAMES, f"{rel}: {frames} frames"
    folder = os.path.dirname(rel)
    if folder == "icons":
        # load_icon squashes any icon into a KEY_LCD square
        assert w == h and w >= protocol.KEY_LCD[0], f"{rel}: {w}x{h}"
    elif folder == "strip":
        # one GIF per strip panel, the size fetch_gifs.py writes too
        assert fmt == "GIF" and (w, h) == protocol.STRIP_LCD, f"{rel}: {fmt} {w}x{h}"


def test_default_strip_segments_are_bundled():
    assert len(ragnarosd.DEFAULT_SEGMENTS) == PANELS
    for gif in ragnarosd.DEFAULT_SEGMENTS:
        assert is_asset(gif), gif


def test_gif_tools_write_what_the_panels_show():
    assert (fetch_gifs.W, fetch_gifs.H) == protocol.STRIP_LCD
    assert (strip_gif.W, strip_gif.H) == ragnarosd.Deck.STRIP_FULL


# -- dry run -------------------------------------------------------------------
class RecordingDev:
    """Stands in for protocol.Ragnaros and keeps the last image per slot."""

    def __init__(self):
        self.keys, self.strip = {}, {}

    def send_image(self, slot, data, strip=False):
        (self.strip if strip else self.keys)[slot] = data

    def flush(self):
        pass

    def set_brightness(self, value):
        pass


@pytest.fixture
def deck_for(monkeypatch):
    def make(name):
        monkeypatch.setattr(ragnarosd.protocol, "Ragnaros", RecordingDev)
        monkeypatch.setattr(ragnarosd, "saved_profile_name", lambda: name)
        deck = ragnarosd.Deck()
        deck.apply_profile()
        return deck
    return make


def assert_jpegs(images, size):
    for slot, data in images.items():
        assert data[:2] == b"\xff\xd8", f"slot {slot}: not a JPEG"
        assert Image.open(io.BytesIO(data)).size == size, f"slot {slot}"


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_profile_paints_every_key_and_panel(name, deck_for):
    deck = deck_for(name)
    dev = deck.dev
    for layer in [None, *deck.layers()]:
        deck.layer = layer
        dev.keys.clear()
        deck.paint_keys()
        wanted = {int(k) for k, spec in deck.active_keys().items() if spec.get("icon")}
        painted = set(dev.keys) | set(deck.key_anims)
        assert wanted <= painted, f"layer {layer}: keys {sorted(wanted - painted)} stay dark"
        assert_jpegs(dev.keys, protocol.KEY_LCD)
        assert all(frames for frames, _, _ in deck.key_anims.values())
    deck.layer = None

    everything = set(range(PANELS))
    dev.strip.clear()
    deck.push_dashboard()
    assert set(dev.strip) == everything
    assert_jpegs(dev.strip, protocol.STRIP_LCD)

    # the GIF face; idle_tick silently gives up on a missing or empty GIF
    dev.strip.clear()
    deck.toggle_dashboard(False)
    deck.idle_faces = lambda: ["gifs"]
    deck.idle_tick(time.monotonic())
    segments = deck.idle_segments()
    assert set(dev.strip) == (set(range(len(segments))) if segments else everything)
    assert_jpegs(dev.strip, protocol.STRIP_LCD)


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_state_icons_exist(name, deck_for):
    """The mic, pomodoro and OBS keys swap icons the profile never names."""
    deck = deck_for(name)
    if deck.mic_key is not None:
        for muted in (True, False):
            deck.dev.keys.clear()
            deck.mic_muted = muted
            deck.repaint_mic()
            assert deck.mic_key in deck.dev.keys, f"no mic icon for muted={muted}"
    if deck.pomo_key is not None:
        deck.dev.keys.clear()
        deck.repaint_pomo()
        assert deck.pomo_key in deck.dev.keys
    for state in ({}, {"streaming": True, "recording": True, "scenes": ["Main"]},
                  {"recording": True, "paused": True}):
        deck.obs_state = state
        deck.repaint_obs()  # a missing icon raises here, as it would on the deck


def all_actions(profile):
    for spec in (profile.get("keys") or {}).values():
        yield spec.get("action")
    for layer in (profile.get("layers") or {}).values():
        for spec in (layer.get("keys") or {}).values():
            yield spec.get("action")
        for spec in (layer.get("knobs") or {}).values():
            yield spec.get("press")
    for spec in (profile.get("knobs") or {}).values():
        yield spec.get("press")
    strip = profile.get("strip") or {}
    yield from (strip.get("touch") or {}).values()
    yield from (strip.get("swipe") or {}).values()


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_obs_keys_reach_obs(name, deck_for, monkeypatch):
    requests = []

    class FakeObs:
        @staticmethod
        def command(request, data=None):
            requests.append((request, data))

        @staticmethod
        def status():
            return {"streaming": False, "recording": False, "paused": False,
                    "scenes": [f"Scene {i}" for i in range(10)]}

    monkeypatch.setattr(ragnarosd, "obsclient", FakeObs)
    deck = deck_for(name)
    warnings = []
    deck.notify = warnings.append
    for action in all_actions(deck.profile):
        if isinstance(action, str) and action.startswith("obs:"):
            requests.clear()
            deck.obs_action(action)
            assert warnings == [], f"{action}: {warnings}"
            assert len(requests) == 1, f"{action} sent no OBS request"
