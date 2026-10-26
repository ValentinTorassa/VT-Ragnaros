import types

import pytest

from ragnaros import protocol


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


# -- opt-in untested product IDs ------------------------------------------------
def test_parse_pid_accepts_the_usual_spellings():
    assert protocol.parse_pid("0x2000") == 0x2000
    assert protocol.parse_pid("2000") == 0x2000
    assert protocol.parse_pid(" 0200:2000 ") == 0x2000
    for bad in ("", "zz", "0x10000", "0", "046d:c08c"):
        with pytest.raises(ValueError):
            protocol.parse_pid(bad)


def test_only_the_ss552_unless_a_tester_opts_in(monkeypatch):
    monkeypatch.delenv(protocol.EXPERIMENTAL_ENV, raising=False)
    assert protocol.product_ids() == (0x3001,)
    monkeypatch.setenv(protocol.EXPERIMENTAL_ENV, "0x2000")
    assert protocol.product_ids() == (0x3001, 0x2000)
    assert protocol.product_ids("0x1000") == (0x3001, 0x1000)  # the flag wins
    assert protocol.product_ids("3001") == (0x3001,)
    monkeypatch.setenv(protocol.EXPERIMENTAL_ENV, "  ")
    assert protocol.product_ids() == (0x3001,)


def fake_libusb(monkeypatch, present, interfaces=(0, 1)):
    """Enough of libusb-1.0 for activate_input(): which PIDs are plugged in and
    which interfaces they have. Records the calls that touch a device."""
    calls = []

    def open_device(context, vid, pid):
        calls.append(("open", vid, pid))
        return 1 if pid in present else None

    def claim(handle, interface):
        if interface not in interfaces:
            return protocol.LIBUSB_ERROR_NOT_FOUND
        calls.append(("claim", interface))
        return 0

    usb = types.SimpleNamespace(
        libusb_init=lambda context: 0,
        libusb_open_device_with_vid_pid=open_device,
        libusb_kernel_driver_active=lambda handle, interface: 0,
        libusb_detach_kernel_driver=lambda handle, interface: 0,
        libusb_claim_interface=claim,
        libusb_release_interface=lambda handle, interface: calls.append(("release", interface)),
        libusb_attach_kernel_driver=lambda handle, interface: 0,
        libusb_control_transfer=lambda *args: 0,
        libusb_interrupt_transfer=lambda *args: 0,
        libusb_close=lambda handle: calls.append(("close",)),
        libusb_exit=lambda context: None,
    )
    monkeypatch.setattr(protocol.ctypes.util, "find_library", lambda name: "libusb-1.0.so.0")
    monkeypatch.setattr(protocol.ctypes, "CDLL", lambda name: usb)
    return calls


def test_the_default_opens_only_the_ss552(monkeypatch):
    calls = fake_libusb(monkeypatch, present={0x3001, 0x2000})
    dev = protocol.Ragnaros()
    assert [c for c in calls if c[0] == "open"] == [("open", 0x0200, 0x3001)]
    assert (dev.pid, dev.experimental, dev.path) == (0x3001, False, "libusb:0200:3001")


def test_the_default_error_is_unchanged(monkeypatch):
    fake_libusb(monkeypatch, present={0x2000})
    with pytest.raises(RuntimeError, match="cannot open Ragnaros USB device"):
        protocol.Ragnaros()


def test_an_opted_in_pid_is_tried_after_the_ss552(monkeypatch):
    calls = fake_libusb(monkeypatch, present={0x2000}, interfaces=(0,))
    dev = protocol.Ragnaros((0x3001, 0x2000))
    assert [c for c in calls if c[0] == "open"] == [("open", 0x0200, 0x3001),
                                                     ("open", 0x0200, 0x2000)]
    assert (dev.pid, dev.experimental, dev.path) == (0x2000, True, "libusb:0200:2000")
    assert dev.claimed == [0]  # a single-interface deck is still worth a try


def test_a_missing_interface_still_fails_the_ss552(monkeypatch):
    calls = fake_libusb(monkeypatch, present={0x3001}, interfaces=(0,))
    with pytest.raises(RuntimeError, match="cannot claim HID interface 1"):
        protocol.Ragnaros((0x3001, 0x2000))
    assert ("release", 0) in calls and ("close",) in calls


def test_nothing_to_open_names_both_ids(monkeypatch):
    fake_libusb(monkeypatch, present=set())
    with pytest.raises(RuntimeError, match="0200:3001 or 0200:2000.*ragnaros diagnose"):
        protocol.Ragnaros((0x3001, 0x2000))


def test_experimental_input_is_logged_raw(capsys):
    report = b"ACK\x00\x00OK\x00\x00\x0b\x01" + bytes(501)
    dev = make_dev()
    dev.transfer = lambda endpoint, payload, timeout: report
    assert dev.poll() == ("unknown", 0x0B, 1)
    assert capsys.readouterr().err == ""
    dev.experimental = True
    dev.poll()
    err = capsys.readouterr().err
    assert "experimental input (512 bytes): 41 43 4b 00 00 4f 4b 00 00 0b 01\n" in err
