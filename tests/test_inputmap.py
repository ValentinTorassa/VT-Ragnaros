import inputmap


def frame(code, state=1, prefix=b"ACK"):
    data = bytearray(prefix + b"\x00" * 9)
    data[9] = code
    data[10] = state
    return bytes(data)


def test_key_events():
    assert inputmap.parse_input(frame(0x01, 1)) == ("key", 0, True)
    assert inputmap.parse_input(frame(0x0A, 0)) == ("key", 9, False)


def test_knob_rotate():
    assert inputmap.parse_input(frame(0xA1)) == ("knob", 0, 1)
    assert inputmap.parse_input(frame(0xA0)) == ("knob", 0, -1)
    assert inputmap.parse_input(frame(0x71)) == ("knob", 3, 1)


def test_knob_press():
    assert inputmap.parse_input(frame(0x37, 1)) == ("knob_press", 0, True)
    assert inputmap.parse_input(frame(0x35, 0)) == ("knob_press", 1, False)


def test_strip_events():
    assert inputmap.parse_input(frame(0x38)) == ("strip_swipe", -1, None)
    assert inputmap.parse_input(frame(0x39)) == ("strip_swipe", 1, None)
    assert inputmap.parse_input(frame(0x42, 1)) == ("strip_touch", 2, True)
    assert inputmap.parse_input(frame(0x40, 0)) == ("strip_touch", 0, False)


def test_garbage_is_ignored():
    assert inputmap.parse_input(b"\x00" * 11) is None
    assert inputmap.parse_input(frame(0x77)) == ("unknown", 0x77, 1)
    assert inputmap.parse_input(b"ACK\x00") is None
