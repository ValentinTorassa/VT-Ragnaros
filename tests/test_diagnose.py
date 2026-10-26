"""`ragnaros diagnose` against a fake sysfs: read-only, and nothing private."""
import builtins
import getpass
import os
import platform
import socket

import pytest

from ragnaros import cli, diagnose, paths

# The SS552's configuration descriptors as sysfs keeps them: device + config,
# a vendor HID interface (EP 0x82 in, 0x03 out) and a boot keyboard (EP 0x81).
SS552_DESCRIPTORS = bytes.fromhex("""
    12 01 00 02 00 00 00 40 00 02 01 30 02 00 01 02
    03 01 09 02 42 00 02 01 00 80 e1 09 04 00 00 02
    03 00 00 00 09 21 00 02 00 01 22 36 00 07 05 82
    03 00 02 01 07 05 03 03 00 04 01 09 04 01 00 01
    03 01 01 00 09 21 00 02 00 01 22 3f 00 07 05 81
    03 08 00 0a""")
REPORT_DESCRIPTOR = bytes.fromhex("06 00 ff 09 01 a1 01 09 02 15 00 26 ff 00 75 08 95 40 81 02 c0")
SERIAL = "SECRET-SERIAL-0042"


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(content, bytes) else "w") as f:
        f.write(content)


def endpoint(interface, address, direction, size, b_interval, interval):
    for key, value in {"bEndpointAddress": address, "direction": direction,
                       "type": "Interrupt", "wMaxPacketSize": size,
                       "bInterval": b_interval, "interval": interval}.items():
        write(interface / f"ep_{address}" / key, value + "\n")


def plug(root, name="5-1.4", vid="0200", pid="2000", busnum=5, devnum=2, driver="usbhid"):
    """A deck in the fake sysfs; with usbhid bound it gets hidraw nodes."""
    dev = root / "sys" / "bus" / "usb" / "devices" / name
    for key, value in {"idVendor": vid, "idProduct": pid, "manufacturer": "HOTSPOTEKUSB",
                       "product": "HOTSPOTEKUSB HID DEMO", "serial": SERIAL,
                       "busnum": str(busnum), "devnum": str(devnum), "speed": "480",
                       "version": " 2.00", "bcdDevice": "0002", "bDeviceClass": "00",
                       "bNumConfigurations": "1", "bNumInterfaces": " 2",
                       "bMaxPower": "450mA"}.items():
        write(dev / key, value + "\n")
    raw = bytearray(SS552_DESCRIPTORS)
    raw[10:12] = int(pid, 16).to_bytes(2, "little")
    write(dev / "descriptors", bytes(raw))
    drivers = root / "sys" / "bus" / "usb" / "drivers" / driver
    drivers.mkdir(parents=True, exist_ok=True)
    for number, (subclass, protocol) in enumerate([("00", "00"), ("01", "01")]):
        intf = dev / f"{name}:1.{number}"
        for key, value in {"bInterfaceNumber": f"{number:02x}", "bInterfaceClass": "03",
                           "bInterfaceSubClass": subclass,
                           "bInterfaceProtocol": protocol}.items():
            write(intf / key, value + "\n")
        os.symlink(drivers, intf / "driver")
        if driver == "usbhid":
            hid = intf / f"0003:{vid.upper()}:{pid.upper()}.000{number + 5}"
            write(hid / "report_descriptor", REPORT_DESCRIPTOR)
            (hid / "hidraw" / f"hidraw{number + 3}").mkdir(parents=True)
            write(root / "dev" / f"hidraw{number + 3}", "")
    endpoint(dev / f"{name}:1.0", "82", "in", "0200", "01", "125us")
    endpoint(dev / f"{name}:1.0", "03", "out", "0400", "01", "125us")
    endpoint(dev / f"{name}:1.1", "81", "in", "0008", "0a", "64ms")
    write(root / "dev" / "bus" / "usb" / f"{busnum:03d}" / f"{devnum:03d}", "")
    return dev


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A machine with the SS552's udev rule and quirk installed and no deck yet."""
    monkeypatch.delenv("RAGNAROS_EXPERIMENTAL_PID", raising=False)
    with open(os.path.join(paths.bundled("udev"), "70-ragnaros.rules")) as f:
        write(tmp_path / "etc" / "udev" / "rules.d" / "70-ragnaros.rules", f.read())
    write(tmp_path / "usr" / "lib" / "udev" / "rules.d" / "50-udev-default.rules",
          'SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", MODE="0664"\n')
    write(tmp_path / "sys" / "module" / "usbhid" / "parameters" / "quirks",
          "0x0200:0x3001:0x00000004,(null),(null),(null)\n")
    write(tmp_path / "etc" / "os-release", 'NAME="Debian"\nPRETTY_NAME="Debian GNU/Linux 13"\n')
    hub = tmp_path / "sys" / "bus" / "usb" / "devices" / "usb5"
    write(hub / "idVendor", "1d6b\n")
    write(hub / "idProduct", "0002\n")
    return tmp_path


def test_an_untested_sibling_gets_everything_needed_to_add_it(root):
    plug(root)
    text, notes, found = diagnose.report(str(root))
    assert found
    assert "#### 0200:2000 HOTSPOTEKUSB HID DEMO\n\nNot supported yet." in text
    assert ("| 0 | 03/00/00 HID | usbhid | 0x03 OUT | Interrupt | 1024 | 125us (bInterval 01) |\n"
            "|  |  |  | 0x82 IN | Interrupt | 512 | 125us (bInterval 01) |") in text
    assert "| 1 | 03/01/01 HID, boot keyboard | usbhid | 0x81 IN | Interrupt | 8 |" in text
    assert ("HID report descriptor, interface 0 (54 bytes declared, HID 2.00), "
            "`/dev/hidraw3` ") in text
    assert "```\n06 00 ff 09 01 a1 01 09 02 15 00 26 ff 00 75 08\n95 40 81 02 c0\n```" in text
    assert "| device node | `/dev/bus/usb/005/002` " in text
    assert "| udev rules | none match |" in text  # 70-ragnaros.rules is for 3001 only
    assert "| usbhid quirk | none |" in text
    assert "| distribution | Debian GNU/Linux 13 |" in text
    assert "| usbhid quirks | `0x0200:0x3001:0x00000004` |" in text
    assert "12 01 00 02 00 00 00 40 00 02 00 20 02 00 01 02" in text  # raw descriptors
    assert "1d6b" not in text  # only vendor 0200 by default
    assert any("ragnarosd --experimental-pid 0x2000" in line for line in notes)


def test_the_report_leaves_out_serial_host_and_user(root, monkeypatch):
    plug(root)
    monkeypatch.setattr(platform, "node", lambda: "secret-hostname")
    monkeypatch.setattr(socket, "gethostname", lambda: "secret-hostname")
    text, notes, _ = diagnose.report(str(root))
    assert "| serial number | present, not shown |" in text
    for private in (SERIAL, "secret-hostname", str(root)):
        assert private not in text and not any(private in line for line in notes)
    if os.getuid() != 0:
        assert getpass.getuser() not in text


def test_accounts_are_named_only_when_they_are_system_ones():
    names = {0: "root", 46: "plugdev", 1000: "alice", 1001: "bob"}

    def lookup(ident):
        return (names[ident],)

    assert diagnose._account(0, lookup, 1000, True) == "root"
    assert diagnose._account(46, lookup, 1000, False) == "plugdev"
    assert diagnose._account(1000, lookup, 1000, True) == "you"
    assert diagnose._account(1001, lookup, 1000, True) == "another user"
    assert diagnose._account(1001, lookup, 1000, False) == "a user group"


def test_the_ss552_without_a_hid_driver(root):
    plug(root, pid="3001", devnum=3, driver="usbfs")
    text, notes, found = diagnose.report(str(root))
    assert found and notes == []  # writable, supported: nothing to do
    assert "Supported (Redragon SS552)." in text
    assert ("HID report descriptor, interface 0 (54 bytes declared, HID 2.00): "
            "no HID driver bound (driver: usbfs).") in text
    assert "| usbhid quirk | `0x00000004` (IGNORE) |" in text
    assert "| udev rules | `/etc/udev/rules.d/70-ragnaros.rules` (hidraw, usb) |" in text


def test_device_picks_one_vid_pid(root):
    plug(root)
    plug(root, name="3-2", vid="046d", pid="c08c", busnum=3, devnum=2)
    text, notes, found = diagnose.report(str(root), (0x046D, 0xC08C))
    assert found and "#### 046d:c08c" in text and "0200:2000" not in text
    assert notes == []  # the experimental test is for vendor 0200 only
    text, notes, found = diagnose.report(str(root), (0x0200, 0x1234))
    assert not found and "No USB device found for 0200:1234." in text


def test_the_hint_grants_access_when_the_node_is_locked(root):
    if os.getuid() == 0:
        pytest.skip("root can open anything")
    plug(root)
    os.chmod(root / "dev" / "bus" / "usb" / "005" / "002", 0o444)
    text, notes, _ = diagnose.report(str(root))
    assert "you: read only" in text
    assert any(line.startswith('  sudo chown "$USER" /dev/bus/usb/005/002 ')
               and line.endswith("# until you unplug it") for line in notes)


def test_an_opted_in_device_says_so(root, monkeypatch):
    plug(root)
    monkeypatch.setenv("RAGNAROS_EXPERIMENTAL_PID", "0x2000")
    text, _, _ = diagnose.report(str(root))
    assert "| `RAGNAROS_EXPERIMENTAL_PID` | `0x2000` |" in text
    assert "opts it into the experimental test" in text


def test_it_never_writes_or_opens_a_device_node(root, monkeypatch):
    plug(root)
    opened = []
    real_open = builtins.open

    def guarded(path, mode="r", *args, **kwargs):
        opened.append((str(path), mode))
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(diagnose, "open", guarded, raising=False)
    diagnose.report(str(root))
    assert opened and all(mode in ("r", "rb") for _, mode in opened)
    assert not [p for p, _ in opened if os.path.relpath(p, root).startswith("dev")]
    assert not [p for p, _ in opened if p.endswith("serial")]


def test_hid_descriptor_lengths_come_from_the_raw_descriptors():
    assert diagnose.hid_descriptors(SS552_DESCRIPTORS) == {0: ("2.00", 54), 1: ("2.00", 63)}
    assert diagnose.hid_descriptors(b"") == {}
    assert diagnose.hid_descriptors(b"\x00\x00") == {}


@pytest.mark.parametrize("rule,expected", [
    ('SUBSYSTEM=="usb", ATTR{idVendor}=="0200", ATTR{idProduct}=="3001", MODE="0660"', []),
    ('SUBSYSTEM=="usb", ATTR{idVendor}=="0200", ATTR{idProduct}=="3001|2000"', ["usb"]),
    ('SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0200", ATTRS{idProduct}=="2*"', ["hidraw"]),
    ('ATTRS{idVendor}=="0200", TAG+="uaccess"', ["any"]),
    ('ENV{ID_VENDOR_ID}=="0200", ENV{ID_MODEL_ID}=="2000"', ["any"]),
    ('# SUBSYSTEM=="usb", ATTR{idVendor}=="0200"', []),
    ('SUBSYSTEM=="usb", ATTR{idVendor}=="046d"', []),
    ('SUBSYSTEM=="usb", \\\n  ATTR{idVendor}=="0200", ATTR{idProduct}=="2000"', ["usb"]),
])
def test_udev_rule_matching(rule, expected):
    assert diagnose.rule_matches(rule, 0x0200, 0x2000) == expected


def test_etc_rules_override_packaged_ones(root):
    write(root / "usr" / "lib" / "udev" / "rules.d" / "70-ragnaros.rules",
          'SUBSYSTEM=="usb", ATTR{idVendor}=="0200", ATTR{idProduct}=="2000"\n')
    assert diagnose.udev_coverage(str(root), 0x0200, 0x2000) == []
    os.remove(root / "etc" / "udev" / "rules.d" / "70-ragnaros.rules")
    assert diagnose.udev_coverage(str(root), 0x0200, 0x2000) == [
        "`/usr/lib/udev/rules.d/70-ragnaros.rules` (usb)"]


def test_cli_diagnose_report_on_stdout_hints_on_stderr(root, monkeypatch, capsys):
    plug(root)
    monkeypatch.setattr(diagnose, "ROOT", str(root))
    assert cli.main(["diagnose"]) == 0
    out, err = capsys.readouterr()
    assert out.startswith("### Ragnaros device report\n")
    assert "ragnarosd --experimental-pid" not in out
    assert "ragnarosd --experimental-pid 0x2000" in err
    assert cli.main(["diagnose", "--device", "0200:1234"]) == 1
    assert "No USB device found for 0200:1234" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["diagnose", "--device", "nope"])


def test_parse_device():
    assert diagnose.parse_device("0200:2000") == (0x0200, 0x2000)
    for bad in ("0200", "0200:", "zz:2000", "0200:12345"):
        with pytest.raises(ValueError):
            diagnose.parse_device(bad)
