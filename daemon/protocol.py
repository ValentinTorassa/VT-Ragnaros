import ctypes
import ctypes.util
import time

from inputmap import parse_input

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


def activate_input():
    library = ctypes.util.find_library("usb-1.0")
    if not library:
        raise RuntimeError("libusb-1.0 is required to activate Ragnaros input")

    usb = ctypes.CDLL(library)
    usb.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    usb.libusb_open_device_with_vid_pid.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16]
    usb.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
    for name in (
        "libusb_kernel_driver_active",
        "libusb_detach_kernel_driver",
        "libusb_claim_interface",
        "libusb_release_interface",
        "libusb_attach_kernel_driver",
    ):
        getattr(usb, name).argtypes = [ctypes.c_void_p, ctypes.c_int]
    usb.libusb_control_transfer.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint8,
        ctypes.c_uint8,
        ctypes.c_uint16,
        ctypes.c_uint16,
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_uint16,
        ctypes.c_uint,
    ]
    usb.libusb_interrupt_transfer.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ubyte,
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint,
    ]
    usb.libusb_close.argtypes = [ctypes.c_void_p]
    usb.libusb_exit.argtypes = [ctypes.c_void_p]

    context = ctypes.c_void_p()
    result = usb.libusb_init(ctypes.byref(context))
    if result < 0:
        raise RuntimeError(f"libusb initialization failed ({result})")

    handle = None
    detached = []
    claimed = []
    try:
        handle = usb.libusb_open_device_with_vid_pid(context, VID, PID)
        if not handle:
            raise RuntimeError("cannot open Ragnaros USB device; check udev permissions")
        for interface in (0, 1):
            if usb.libusb_kernel_driver_active(handle, interface) == 1:
                result = usb.libusb_detach_kernel_driver(handle, interface)
                if result < 0:
                    raise RuntimeError(f"cannot detach HID interface {interface} ({result})")
                detached.append(interface)
        for interface in (0, 1):
            result = usb.libusb_claim_interface(handle, interface)
            if result < 0:
                raise RuntimeError(f"cannot claim HID interface {interface} ({result})")
            claimed.append(interface)
    except Exception:
        if handle:
            for interface in reversed(claimed):
                usb.libusb_release_interface(handle, interface)
            for interface in reversed(detached):
                usb.libusb_attach_kernel_driver(handle, interface)
            usb.libusb_close(handle)
        usb.libusb_exit(context)
        raise
    return usb, context, handle, detached, claimed


class Ragnaros:
    def __init__(self):
        self.usb, self.context, self.handle, self.detached, self.claimed = activate_input()
        self.path = f"libusb:{VID:04x}:{PID:04x}"
        self._initialized = False

    def close(self):
        if not self.handle:
            return
        for interface in reversed(self.claimed):
            self.usb.libusb_release_interface(self.handle, interface)
        for interface in reversed(self.detached):
            self.usb.libusb_attach_kernel_driver(self.handle, interface)
        self.usb.libusb_close(self.handle)
        self.usb.libusb_exit(self.context)
        self.handle = None

    def control(self, request_type, request, value, index, data_or_length, timeout=1000):
        if isinstance(data_or_length, int):
            buffer = (ctypes.c_uint8 * data_or_length)()
            length = data_or_length
        else:
            payload = bytes(data_or_length)
            buffer = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
            length = len(payload)
        result = self.usb.libusb_control_transfer(
            self.handle, request_type, request, value, index, buffer, length, timeout
        )
        if result < 0:
            raise RuntimeError(f"Ragnaros control transfer failed ({result})")
        return bytes(buffer[:result])

    def get_feature_report(self, report_id, length):
        return self.control(0xA1, 0x01, (0x03 << 8) | report_id, 0, length)

    def get_input_report(self, report_id, length):
        return self.control(0xA1, 0x01, (0x01 << 8) | report_id, 0, length)

    def send_feature_report(self, payload):
        self.control(0x21, 0x09, (0x03 << 8) | (payload[0] if payload else 0), 0, payload)

    def transfer(self, endpoint, payload, timeout):
        buffer = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
        transferred = ctypes.c_int()
        result = self.usb.libusb_interrupt_transfer(
            self.handle,
            endpoint,
            buffer,
            len(buffer),
            ctypes.byref(transferred),
            timeout,
        )
        if result == -7:
            return None
        if result < 0:
            raise RuntimeError(f"Ragnaros endpoint {endpoint:#04x} transfer failed ({result})")
        if not endpoint & 0x80 and transferred.value != len(payload):
            raise RuntimeError(
                f"short write to Ragnaros endpoint {endpoint:#04x} "
                f"({transferred.value}/{len(payload)} bytes)"
            )
        return bytes(buffer[: transferred.value])

    def write(self, payload):
        buf = bytes(payload) + b"\x00" * (1 + PACKET_SIZE - len(payload))
        if len(buf) != PACKET_SIZE + 1:
            raise ValueError("Ragnaros output report exceeds 1024 bytes")
        self.transfer(0x03, buf[1:], 1000)

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
        if size > 0xFFFF:
            # the BAT header carries the length in two bytes; a larger
            # payload would wrap and leave the firmware parser desynced
            raise ValueError(f"image payload too large for the deck ({size} bytes)")
        self.command(0x42, 0x41, 0x54, 0x00, 0x00, size >> 8, size & 0xFF, slot + 1)
        for offset in range(0, size, PACKET_SIZE):
            chunk = image_data[offset : offset + PACKET_SIZE]
            self.write(b"\x00" + chunk)

    def flush(self):
        self.command(0x53, 0x54, 0x50)

    def set_mode(self, mode):
        self.command(0x4D, 0x4F, 0x44, 0x00, 0x00, 0x30 + mode)

    def sleep(self):
        self.initialize()
        self.command(0x48, 0x41, 0x4E)

    def reset_display(self):
        """Sleep the display pipeline and wake it fresh.

        Recovers panels hung to the point of showing nothing while USB
        still ACKs every write (observed after firmware parser desyncs).
        """
        self.sleep()
        time.sleep(2)
        self._initialized = False
        self.initialize()
        self.set_brightness(100)

    def keep_alive(self):
        self.initialize()
        self.command(0x43, 0x4F, 0x4E, 0x4E, 0x45, 0x43, 0x54)

    def shutdown(self):
        self.initialize()
        self.command(0x43, 0x4C, 0x45, 0x00, 0x00, 0x44, 0x43)
        self.command(0x48, 0x41, 0x4E)

    def poll(self, timeout=10):
        data = self.transfer(0x82, bytes(READ_SIZE), timeout)
        if data is None:
            return None
        return parse_input(data)
