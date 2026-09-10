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
