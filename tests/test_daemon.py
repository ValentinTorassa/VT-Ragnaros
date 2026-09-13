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
    deck._run = lambda cmd, timeout=1.0: (
        0, "spotify\tPlaying\tSong\tArtist\t27862750\t50150000\t")
    player = deck.poll_player()
    assert player["position"] == pytest.approx(27.86275)
    assert player["length"] == pytest.approx(50.15)


def test_poll_player_skips_non_playing_entries():
    deck = ragnarosd.Deck.__new__(ragnarosd.Deck)
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
