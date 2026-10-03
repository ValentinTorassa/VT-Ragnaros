INPUT_CODES = {
    "button": {i: i for i in range(1, 11)},
    "knob_press": {0x37: 0, 0x35: 1, 0x33: 2, 0x36: 3},
    "knob_rotate": {0xA0: (0, -1), 0xA1: (0, 1), 0x50: (1, -1), 0x51: (1, 1),
                    0x90: (2, -1), 0x91: (2, 1), 0x70: (3, -1), 0x71: (3, 1)},
    "strip_swipe": {0x38: -1, 0x39: 1},
    "strip_touch": {0x40: 0, 0x41: 1, 0x42: 2, 0x43: 3},
}


def parse_input(data):
    if len(data) < 11 or data[:3] != b"ACK":
        return None
    code, state = data[9], data[10]
    if code in INPUT_CODES["knob_rotate"]:
        knob, direction = INPUT_CODES["knob_rotate"][code]
        return ("knob", knob, direction)
    if code in INPUT_CODES["knob_press"]:
        return ("knob_press", INPUT_CODES["knob_press"][code], bool(state))
    if code in INPUT_CODES["strip_swipe"]:
        return ("strip_swipe", INPUT_CODES["strip_swipe"][code], None)
    if code in INPUT_CODES["strip_touch"]:
        return ("strip_touch", INPUT_CODES["strip_touch"][code], bool(state))
    if 1 <= code <= 10:
        return ("key", code - 1, bool(state))
    return ("unknown", code, state)
