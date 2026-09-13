import pytest

import ragnarosd


class FakeDev:
    def initialize(self):
        pass

    def reset_display(self):
        pass

    def close(self):
        pass


def test_wait_for_device_retries_until_present(monkeypatch):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("cannot open Ragnaros USB device; check udev permissions")
        return FakeDev()

    monkeypatch.setattr(ragnarosd.protocol, "Ragnaros", flaky)
    monkeypatch.setattr(ragnarosd.time, "sleep", lambda s: None)
    deck = ragnarosd.Deck()
    assert calls["n"] == 3
    assert isinstance(deck.dev, FakeDev)
    deck.dev.close()

def test_wait_for_device_exits_without_libusb(monkeypatch):
    def broken():
        raise RuntimeError("libusb-1.0 is required to activate Ragnaros input")

    monkeypatch.setattr(ragnarosd.protocol, "Ragnaros", broken)
    try:
        ragnarosd.Deck()
    except SystemExit as error:
        assert "libusb" in str(error)
    else:
        raise AssertionError("expected SystemExit when libusb is missing")


def test_reconnect_uses_wait_loop(monkeypatch):
    monkeypatch.setattr(ragnarosd.protocol, "Ragnaros", lambda: FakeDev())
    monkeypatch.setattr(ragnarosd.time, "sleep", lambda s: None)

    class BareDeck(ragnarosd.Deck):
        def apply_profile(self):
            pass

    deck = BareDeck.__new__(BareDeck)
    deck.dev = FakeDev()
    deck.reconnect()
    assert isinstance(deck.dev, FakeDev)
    assert deck.mic_muted is None
    assert deck.obs_state is None


def test_poll_player_converts_microseconds_to_seconds():
    """playerctl reports position and mpris:length in microseconds."""
    deck = ragnarosd.Deck.__new__(ragnarosd.Deck)
    deck.profile = {}
    deck._run = lambda cmd, timeout=1.0: (
        0, "spotify\tPlaying\tSong\tArtist\t27862750\t50150000\t")
    player = deck.poll_player()
    assert player["position"] == pytest.approx(27.86275)
    assert player["length"] == pytest.approx(50.15)


def test_poll_player_skips_non_playing_entries():
    deck = ragnarosd.Deck.__new__(ragnarosd.Deck)
    deck.profile = {}
    deck._run = lambda cmd, timeout=1.0: (0, "\n".join([
        "firefox\tPaused\tTab\t\t0\t\t",
        "spotify\tPlaying\tSong\tArtist\t1000000\t2000000\t",
    ]))
    player = deck.poll_player()
    assert player["title"] == "Song"
    assert player["position"] == pytest.approx(1.0)


def test_push_strip_frame_keeps_segment_order():
    """Slot 0 is the leftmost panel; each crop is rotated on its own."""
    import io

    from PIL import Image

    quarters = [(220, 20, 20), (20, 200, 20), (20, 20, 220), (220, 200, 20)]
    frame = Image.new("RGB", (704, 124))
    for i, color in enumerate(quarters):
        frame.paste(Image.new("RGB", (176, 124), color), (i * 176, 0))

    sent = {}

    class RecordingDev:
        def send_image(self, seg, data, strip=False):
            sent[seg] = data

        def flush(self):
            pass

    deck = ragnarosd.Deck.__new__(ragnarosd.Deck)
    deck.dev = RecordingDev()
    deck.push_strip_frame(frame)

    assert sorted(sent) == [0, 1, 2, 3]
    for seg, color in enumerate(quarters):
        panel = Image.open(io.BytesIO(sent[seg])).rotate(180)  # as the panel shows it
        assert panel.size == (176, 124)
        for channel, expected in zip(panel.getpixel((88, 62)), color):
            assert abs(channel - expected) < 12


def bare_deck(profile=None, **state):
    """A Deck with no hardware: enough state for the pure logic paths."""
    deck = ragnarosd.Deck.__new__(ragnarosd.Deck)
    deck.profile = profile if profile is not None else {"_name": "test"}
    deck.layer = deck.layer_hold = deck.pinned = deck.player = None
    deck.dash_cards = None
    deck.alert = None
    deck.alert_next = 0.0
    deck.control = None
    deck.locked = False
    deck.idle_face = None
    deck.idle_playing = False
    deck.dash_next = deck.np_next = deck.gif_next = deck.overlay_until = 0.0
    deck.brightness = 100
    deck.pomo = deck.obs_state = None
    deck._last_toast = ("", 0.0)
    deck.log_usage = lambda *a, **k: None
    deck.paint_keys = lambda: None
    deck.__dict__.update(state)
    return deck


PROFILE = {
    "_name": "test",
    "keys": {"0": {"action": "base-zero"}, "1": {"action": "base-one"}},
    "knobs": {"0": {"press": "base-knob"}},
    "layers": {"media": {"keys": {"0": {"action": "layer-zero"}},
                         "knobs": {"0": {"press": "layer-knob"}}}},
}


def test_layer_keys_lay_over_the_base_profile():
    deck = bare_deck(PROFILE)
    assert deck.active_keys()["0"]["action"] == "base-zero"
    deck.set_layer("media")
    assert deck.active_keys()["0"]["action"] == "layer-zero"
    assert deck.active_keys()["1"]["action"] == "base-one"  # falls through
    assert deck.active_knobs()["0"]["press"] == "layer-knob"


def test_unknown_layer_is_refused():
    deck = bare_deck(PROFILE)
    assert deck.set_layer("nope") is False
    assert deck.layer is None
    assert deck.set_layer("base") is True


def test_layer_action_toggles():
    deck = bare_deck(PROFILE)
    deck.run_deck_action("layer:media")
    assert deck.layer == "media"
    deck.run_deck_action("layer:media")
    assert deck.layer is None


def test_a_dashboard_view_key_opens_and_closes_itself():
    deck = bare_deck(PROFILE)
    deck.run_deck_action("dashboard:cpu,ram,temp")
    assert deck.pinned == "dashboard" and deck.dash_cards == ["cpu", "ram", "temp"]
    deck.run_deck_action("dashboard:net")  # a different view stays pinned
    assert deck.pinned == "dashboard" and deck.dash_cards == ["net"]
    deck.run_deck_action("dashboard:net")  # the same view again puts it away
    assert deck.pinned is None


def test_a_profile_can_own_the_strip():
    deck = bare_deck(dict(PROFILE, strip={"pinned": "dashboard"}))
    deck.paint_keys = lambda: None
    deck.strip_tick = lambda now: None
    deck.apply_profile()
    assert deck.pinned == "dashboard"


def test_tapping_the_last_panel_toggles_the_dashboard():
    deck = bare_deck(PROFILE)
    deck.strip_touch(3, ("strip_touch", 3, True))
    assert deck.pinned == "dashboard"
    deck.strip_touch(0, ("strip_touch", 0, True))  # any tap puts it away again
    assert deck.pinned is None


def test_taps_control_the_player_when_one_is_playing(monkeypatch):
    ran = []
    monkeypatch.setattr(ragnarosd, "run_action", ran.append)
    deck = bare_deck(PROFILE, player={"title": "x"})
    for idx in (0, 1, 2):
        deck.strip_touch(idx, ("strip_touch", idx, True))
    assert ran == ["playerctl play-pause", "playerctl previous", "playerctl next"]


def test_configured_touch_wins_over_the_defaults(monkeypatch):
    ran = []
    monkeypatch.setattr(ragnarosd, "run_action", ran.append)
    profile = dict(PROFILE, strip={"touch": {"3": "custom-action"}})
    deck = bare_deck(profile)
    deck.strip_touch(3, ("strip_touch", 3, True))
    assert ran == ["custom-action"] and deck.pinned is None


def test_swipe_cycles_profiles(monkeypatch):
    monkeypatch.setattr(ragnarosd, "available_profiles", lambda: ["a", "b", "c"])
    switched = []
    deck = bare_deck(dict(PROFILE, _name="b"))
    deck.switch_profile = switched.append
    deck.strip_swipe(1, ("strip_swipe", 1, None))
    deck.strip_swipe(-1, ("strip_swipe", -1, None))
    assert switched == ["c", "a"]


def test_idle_faces_are_validated():
    assert bare_deck({"_name": "t"}).idle_faces() == list(ragnarosd.DEFAULT_IDLE_FACES)
    assert bare_deck({"strip": {"idle": "dashboard"}}).idle_faces() == ["dashboard"]
    assert bare_deck({"strip": {"idle": ["nonsense"]}}).idle_faces() == \
        list(ragnarosd.DEFAULT_IDLE_FACES)


def test_the_shell_notification_echo_is_dropped():
    shown = []
    deck = bare_deck(PROFILE)
    deck.show_toast = lambda *a, **k: shown.append(a)
    payload = {"app": "Signal", "summary": "hola", "body": "que tal"}
    deck.on_notification(payload)
    deck.on_notification(payload)  # the bus carries every Notify twice
    assert len(shown) == 1


def test_our_own_notifications_never_bounce_back():
    shown = []
    deck = bare_deck(dict(PROFILE, notifications={"ignore": ["muted"]}))
    deck.show_toast = lambda *a, **k: shown.append(a)
    deck.on_notification({"app": "Ragnaros", "summary": "Pomodoro", "body": ""})
    deck.on_notification({"app": "muted", "summary": "x", "body": ""})
    assert shown == []


def test_control_status_and_errors(monkeypatch):
    monkeypatch.setattr(ragnarosd, "available_profiles", lambda: ["test"])
    deck = bare_deck(PROFILE)
    status = deck.handle_control(["status"])
    assert status["ok"] and status["layer"] == "base" and status["strip"] == "keys"
    assert deck.handle_control([])["ok"] is False
    assert deck.handle_control(["nonsense"])["ok"] is False
    assert deck.handle_control(["profile", "ghost"])["ok"] is False
    assert deck.handle_control(["layer", "media"]) == {"ok": True, "layer": "media"}
    reply = deck.handle_control(["dashboard", "on"])
    assert reply["ok"] and reply["dashboard"] is True
    assert deck.handle_control(["dashboard", "cpu,ram"])["cards"] == ["cpu", "ram"]


def test_idle_rotation_period_is_per_profile():
    assert bare_deck({"_name": "t"}).idle_face_seconds() == ragnarosd.IDLE_FACE_SECONDS
    assert bare_deck({"strip": {"idle_seconds": 90}}).idle_face_seconds() == 90.0
    assert bare_deck({"strip": {"idle_seconds": "nope"}}).idle_face_seconds() == \
        ragnarosd.IDLE_FACE_SECONDS
    assert bare_deck({"strip": {"idle_seconds": 0}}).idle_face_seconds() == 3.0


def test_an_alert_owns_the_strip_until_a_press_clears_it(monkeypatch):
    ran = []
    monkeypatch.setattr(ragnarosd, "run_action", ran.append)
    deck = bare_deck(PROFILE)
    deck.set_alert("claude", "Claude terminó", "VT-Ragnaros")
    assert deck.strip_state() == "alert"
    deck.handle_event(("key", 0, True))
    assert deck.alert is None
    assert ran == []  # the press that dismisses does nothing else
    deck.handle_event(("key", 0, True))
    assert ran == ["base-zero"]  # the next one works normally


def test_a_grabbing_watcher_suppresses_profile_actions(monkeypatch):
    ran = []
    monkeypatch.setattr(ragnarosd, "run_action", ran.append)

    class Grabber:
        def __init__(self):
            self.subscribers = [object()]
            self.sent = []

        def broadcast(self, event):
            self.sent.append(event)

        def grabbed(self):
            return True

    deck = bare_deck(PROFILE, control=Grabber())
    deck.handle_event(("key", 0, True))
    assert ran == []                              # the script owns the deck
    assert deck.control.sent[0]["type"] == "key"  # but still sees the press


def test_control_alert_and_watch_commands():
    deck = bare_deck(PROFILE)
    assert deck.handle_control(["alert", "Claude terminó", "VT-Ragnaros"])["ok"]
    assert deck.alert["summary"] == "Claude terminó"
    reply = deck.handle_control(["watch", "--grab"])
    assert reply["_stream"] == {"grab": True}
    assert deck.handle_control(["alert", "--clear"])["cleared"] is True
    assert deck.alert is None
