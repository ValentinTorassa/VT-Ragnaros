import glob
import os

VID = 0x0200
PID = 0x3001

KEY_ROWS = 2
KEY_COLS = 5
KEY_COUNT = KEY_ROWS * KEY_COLS
KEY_LCD = (96, 96)
STRIP_LCD = (854, 120)
KNOB_COUNT = 4


def find_hidraw_nodes():
    nodes = []
    for uevent in glob.glob("/sys/class/hidraw/hidraw*/device/uevent"):
        try:
            with open(uevent) as f:
                data = f.read().replace(":", "")
        except OSError:
            continue
        if f"{VID:08X}" in data and f"{PID:08X}" in data:
            nodes.append("/dev/" + uevent.split("/")[4])
    return sorted(nodes)


class RagnarosProtocol:
    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)

    def close(self):
        os.close(self.fd)

    def set_key_image(self, key, rgb_bytes):
        raise NotImplementedError(
            "image packet format unknown: capture with usbmon while the official software writes a key"
        )

    def set_strip_image(self, rgb_bytes):
        raise NotImplementedError(
            "image packet format unknown: capture with usbmon while the official software writes the strip"
        )

    def set_brightness(self, percent):
        raise NotImplementedError

    def poll(self):
        try:
            data = os.read(self.fd, 512)
        except BlockingIOError:
            return None
        return self.parse_event(data)

    @staticmethod
    def parse_event(data):
        raise NotImplementedError(
            "event report format unknown: press each key and turn each knob while logging hidraw"
        )
