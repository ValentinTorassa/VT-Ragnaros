import glob
import os

VID = 0x0200
PID = 0x3001
PACKET_SIZE = 1024
READ_SIZE = 512

KEY_ROWS = 2
KEY_COLS = 5
KEY_COUNT = KEY_ROWS * KEY_COLS
KNOB_COUNT = 4
KEY_LCD = (112, 112)
STRIP_LCD = (176, 124)
ROTATION = 180

KEY_TO_SLOT = {0: 10, 1: 11, 2: 12, 3: 13, 4: 14, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9}
STRIP_TO_SLOT = {0: 0, 1: 1, 2: 2, 3: 3}

CRT = (0x43, 0x52, 0x54)


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


def find_vendor_node():
    for node in find_hidraw_nodes():
        desc = f"/sys/class/hidraw/{node.split('/')[-1]}/device/report_descriptor"
        try:
            with open(desc, "rb") as f:
                if f.read(4) == b"\x06\xa0\xff\x09":
                    return node
        except OSError:
            continue
    return None


class Ragnaros:
    def __init__(self, path=None):
        self.path = path or find_vendor_node()
        if not self.path:
            raise RuntimeError("Ragnaros vendor interface not found")
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        self._initialized = False

    def close(self):
        os.close(self.fd)

    def write(self, payload):
        buf = bytes(payload) + b"\x00" * (1 + PACKET_SIZE - len(payload))
        os.write(self.fd, buf)

    def command(self, *tail):
        self.write([0x00, *CRT, 0x00, 0x00, *tail])

    def initialize(self):
        if self._initialized:
            return
        self._initialized = True
        self.command(0x44, 0x49, 0x53)
        self.command(0x4C, 0x49, 0x47, 0x00, 0x00, 0x00, 0x00)

    def set_brightness(self, percent):
        self.initialize()
        self.command(0x4C, 0x49, 0x47, 0x00, 0x00, max(0, min(100, percent)))

    def set_led_brightness(self, percent):
        self.initialize()
        self.command(0x4C, 0x42, 0x4C, 0x49, 0x47, max(0, min(100, percent)))

    def set_led_colors(self, colors):
        self.initialize()
        rgb = [c for color in colors for c in color]
        self.command(0x53, 0x45, 0x54, 0x4C, 0x42, *rgb)

    def clear_key(self, key):
        self.initialize()
        self.command(0x43, 0x4C, 0x45, 0x00, 0x00, 0x00, 0xFF if key == 0xFF else key + 1)

    def clear_all(self):
        self.initialize()
        self.clear_key(0xFF)
        self.command(0x53, 0x54, 0x50)

    def send_image(self, key, image_data, strip=False):
        self.initialize()
        slot = (STRIP_TO_SLOT if strip else KEY_TO_SLOT).get(key)
        if slot is None:
            raise ValueError(f"unknown {'strip segment' if strip else 'key'} {key}")
        size = len(image_data)
        self.command(0x42, 0x41, 0x54, 0x00, 0x00, size >> 8, size & 0xFF, slot + 1)
        for offset in range(0, size, PACKET_SIZE):
            chunk = image_data[offset : offset + PACKET_SIZE]
            os.write(self.fd, b"\x00" + chunk + b"\x00" * (PACKET_SIZE - len(chunk)))

    def flush(self):
        self.command(0x53, 0x54, 0x50)

    def set_mode(self, mode):
        self.command(0x4D, 0x4F, 0x44, 0x00, 0x00, 0x30 + mode)

    def sleep(self):
        self.initialize()
        self.command(0x48, 0x41, 0x4E)

    def keep_alive(self):
        self.initialize()
        self.command(0x43, 0x4F, 0x4E, 0x4E, 0x45, 0x43, 0x54)

    def shutdown(self):
        self.initialize()
        self.command(0x43, 0x4C, 0x45, 0x00, 0x00, 0x44, 0x43)
        self.command(0x48, 0x41, 0x4E)

    def poll(self):
        try:
            data = os.read(self.fd, READ_SIZE)
        except BlockingIOError:
            return None
        if len(data) > 10 and data[:3] == b"ACK":
            return (data[9], data[10])
        return ("raw", data[:16].hex())
