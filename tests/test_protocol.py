import protocol


def make_dev():
    """A Ragnaros instance with the USB layer stubbed out (no hardware)."""
    dev = protocol.Ragnaros.__new__(protocol.Ragnaros)
    dev.usb = dev.context = None
    dev.handle = object()
    dev.detached = []
    dev.claimed = []
    dev._initialized = False
    dev.writes = []
    dev.write = lambda payload: dev.writes.append(bytes(payload))
    return dev


def test_command_header_layout():
    dev = make_dev()
    dev.initialize()
    # every command is [report 0x00, "CRT", 0x00, 0x00, ...tail]
    assert dev.writes[0][:6] == b"\x00CRT\x00\x00"
    assert dev.writes[0][6:] == bytes([0x44, 0x49, 0x53])  # DIS
    assert dev.writes[1][6:] == bytes([0x4C, 0x49, 0x47, 0, 0, 0, 0])  # LIG


def test_keep_alive_is_connect():
    dev = make_dev()
    dev.keep_alive()
    assert dev.writes[-1] == b"\x00CRT\x00\x00CONNECT"


def test_reset_display_sleeps_wakes_and_restores_brightness(monkeypatch):
    dev = make_dev()
    monkeypatch.setattr(protocol.time, "sleep", lambda _: None)
    dev.reset_display()
    assert [write[6:] for write in dev.writes] == [
        b"DIS",
        b"LIG\x00\x00\x00\x00",
        b"HAN",
        b"DIS",
        b"LIG\x00\x00\x00\x00",
        b"LIG\x00\x00\x64",
    ]


def test_flush_is_stp():
    dev = make_dev()
    dev.flush()
    assert dev.writes[-1] == b"\x00CRT\x00\x00STP"


def test_send_image_key_slot_and_chunking():
    dev = make_dev()
    payload = bytes(range(256)) * 12  # 3072 bytes -> 3 chunks
    dev.send_image(0, payload)  # key 0 -> slot 10 -> header byte slot+1
    header = dev.writes[2]  # writes 0-1 are the initialize() commands
    assert header[:6] == b"\x00CRT\x00\x00"
    assert header[6:9] == b"BAT"
    assert (header[11] << 8) | header[12] == len(payload)
    assert header[13] == protocol.KEY_TO_SLOT[0] + 1
    chunks = dev.writes[3:]
    assert len(chunks) == 3
    assert all(c[0] == 0x00 for c in chunks)
    assert b"".join(c[1:] for c in chunks)[:len(payload)] == payload


def test_send_image_strip_slots():
    dev = make_dev()
    for seg in range(4):
        dev.writes.clear()
        dev.send_image(seg, b"\xff" * 10, strip=True)
        bat = next(w for w in dev.writes if w[6:9] == b"BAT")
        assert bat[13] == protocol.STRIP_TO_SLOT[seg] + 1


def test_send_image_rejects_unknown_key():
    dev = make_dev()
    try:
        dev.send_image(42, b"x")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown key")
