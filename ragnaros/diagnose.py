"""`ragnaros diagnose`: a device report to paste into an issue.

Read-only: everything comes from sysfs, the /dev nodes' permissions and the
udev rules directories. The device is never opened, so it needs no root and
is safe while ragnarosd owns the deck. The serial number, the hostname and
user names are left out.

By default it reports every USB device under vendor 0200 (the SS552 and its
siblings); `--device VID:PID` picks any other one.
"""
import ctypes.util
import fnmatch
import grp
import os
import platform
import pwd
import re
import stat
import sys

from . import __version__, protocol

ROOT = "/"
SUPPORTED = {(protocol.VID, protocol.PID): "Redragon SS552"}
UDEV_DIRS = ("etc/udev/rules.d", "run/udev/rules.d", "usr/local/lib/udev/rules.d",
             "usr/lib/udev/rules.d", "lib/udev/rules.d")
HID_DEVICE = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}\.[0-9A-Fa-f]+$")
QUIRK = re.compile(r"^0x([0-9a-f]+):0x([0-9a-f]+):0x([0-9a-f]+)$", re.I)
QUIRK_NAMES = {0x4: "IGNORE"}
CLASSES = {"03": "HID", "ff": "vendor specific"}
BOOT_PROTOCOLS = {("01", "01"): "boot keyboard", ("01", "02"): "boot mouse"}
RULE_MATCH = re.compile(
    r'\b(ATTRS?\{idVendor\}|ATTRS?\{idProduct\}|ENV\{ID_VENDOR_ID\}|ENV\{ID_MODEL_ID\}'
    r'|SUBSYSTEMS?)\s*==\s*"([^"]*)"')


def parse_device(text):
    """'0200:2000' -> (0x0200, 0x2000)."""
    vendor, sep, product = text.strip().lower().partition(":")
    try:
        ids = int(vendor, 16), int(product, 16)
    except ValueError:
        ids = None
    if not sep or ids is None or not all(0 <= i <= 0xFFFF for i in ids):
        raise ValueError(f"expected VID:PID in hex, e.g. 0200:2000, not {text!r}")
    return ids


def _path(root, *parts):
    return os.path.join(root, *parts)


def read_attr(directory, name):
    try:
        with open(os.path.join(directory, name), errors="replace") as f:
            return f.read().strip()
    except OSError:
        return None


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def hexdump(data, width=16):
    return "\n".join(data[i:i + width].hex(" ") for i in range(0, len(data), width))


# -- finding devices --------------------------------------------------------------
def find_devices(root, vid, pid=None):
    """sysfs directories of the USB devices with this vendor (and product)."""
    base = _path(root, "sys", "bus", "usb", "devices")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    found = []
    for name in names:
        if ":" in name:  # an interface, not a device
            continue
        directory = os.path.realpath(os.path.join(base, name))
        try:
            ids = int(read_attr(directory, "idVendor") or "", 16), \
                int(read_attr(directory, "idProduct") or "", 16)
        except ValueError:
            continue
        if ids[0] == vid and (pid is None or ids[1] == pid):
            found.append(directory)
    return found


def interfaces(directory):
    """Each interface of the device: class, driver, endpoints and HID children."""
    name = os.path.basename(directory)
    result = []
    for entry in sorted(os.listdir(directory)):
        if not entry.startswith(name + ":"):
            continue
        path = os.path.join(directory, entry)
        driver = os.path.realpath(os.path.join(path, "driver"))
        endpoints = []
        for ep in sorted(os.listdir(path)):
            if ep.startswith("ep_"):
                endpoints.append({k: read_attr(os.path.join(path, ep), k) for k in (
                    "bEndpointAddress", "direction", "type", "wMaxPacketSize",
                    "bInterval", "interval")})
        hid = []
        for child in sorted(os.listdir(path)):
            if HID_DEVICE.match(child):
                hid_dir = os.path.join(path, child)
                try:
                    nodes = sorted(os.listdir(os.path.join(hid_dir, "hidraw")))
                except OSError:
                    nodes = []
                hid.append({"report_descriptor":
                            read_bytes(os.path.join(hid_dir, "report_descriptor")),
                            "hidraw": nodes})
        result.append({
            "number": read_attr(path, "bInterfaceNumber"),
            "class": read_attr(path, "bInterfaceClass"),
            "subclass": read_attr(path, "bInterfaceSubClass"),
            "protocol": read_attr(path, "bInterfaceProtocol"),
            "driver": os.path.basename(driver) if os.path.lexists(
                os.path.join(path, "driver")) else None,
            "endpoints": endpoints,
            "hid": hid,
        })
    return result


def hid_descriptors(raw):
    """{interface number: (bcdHID, report descriptor length)} from the raw
    configuration descriptors, which sysfs keeps even with no driver bound."""
    found = {}
    interface = None
    i = 0
    while raw and i + 2 <= len(raw):
        length, kind = raw[i], raw[i + 1]
        if length < 2:
            break
        if kind == 0x04 and length >= 3:
            interface = raw[i + 2]
        elif kind == 0x21 and length >= 9 and interface is not None:
            bcd = raw[i + 3] << 8 | raw[i + 2]
            for j in range(i + 6, i + length - 2, 3):
                if raw[j] == 0x22:
                    found[interface] = (f"{bcd >> 8:x}.{bcd & 0xFF:02x}",
                                        raw[j + 1] | raw[j + 2] << 8)
        i += length
    return found


# -- permissions, udev, quirks ----------------------------------------------------------
def _account(ident, lookup, mine, users):
    """A system account by name; a person's account only as "you" or anonymous."""
    if ident == mine and ident != 0:
        return "you" if users else "your group"
    if ident < 1000:
        try:
            return lookup(ident)[0]
        except KeyError:
            return str(ident)
    return "another user" if users else "a user group"


def node_access(path):
    """'crw-rw---- root:plugdev, ACL, you: read+write', or None if absent."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    owner = _account(st.st_uid, pwd.getpwuid, os.getuid(), True)
    group = _account(st.st_gid, grp.getgrgid, os.getgid(), False)
    try:
        acl = ", ACL" if "system.posix_acl_access" in os.listxattr(path) else ""
    except OSError:
        acl = ""
    if os.access(path, os.R_OK | os.W_OK):
        you = "read+write"
    elif os.access(path, os.R_OK):
        you = "read only"
    else:
        you = "no access"
    return f"{stat.filemode(st.st_mode)} {owner}:{group}{acl}, you: {you}"


def usbhid_quirks(root):
    """[(vid, pid, flags)] the running usbhid was loaded with, or None if unknown."""
    text = read_attr(_path(root, "sys", "module", "usbhid", "parameters"), "quirks")
    if text is None:
        return None
    quirks = []
    for item in text.split(","):
        match = QUIRK.match(item.strip())
        if match:
            quirks.append(tuple(int(g, 16) for g in match.groups()))
    return quirks


def udev_rule_files(root):
    """The rules files udev uses: the first of each name, /etc before /usr/lib."""
    chosen = {}
    for directory in UDEV_DIRS:
        try:
            names = os.listdir(_path(root, directory))
        except OSError:
            continue
        for name in names:
            if name.endswith(".rules") and name not in chosen:
                chosen[name] = _path(root, directory, name)
    return [chosen[name] for name in sorted(chosen)]


def _matches(pattern, value):
    return any(fnmatch.fnmatchcase(value, alt) for alt in pattern.split("|"))


def rule_matches(text, vid, pid):
    """Subsystems of the rules in this file that name this vendor and product
    (a rule naming only the vendor covers every product)."""
    found = []
    for line in text.replace("\\\n", " ").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        keys = {"vendor": [], "product": [], "subsystem": []}
        for key, value in RULE_MATCH.findall(line):
            if "Vendor" in key or "VENDOR" in key:
                keys["vendor"].append(value)
            elif "SUBSYSTEM" in key:
                keys["subsystem"].append(value)
            else:
                keys["product"].append(value)
        if not keys["vendor"]:
            continue
        if all(_matches(p, f"{vid:04x}") for p in keys["vendor"]) and \
                all(_matches(p, f"{pid:04x}") for p in keys["product"]):
            subsystem = "/".join(keys["subsystem"]) or "any"
            if subsystem not in found:
                found.append(subsystem)
    return found


def udev_coverage(root, vid, pid):
    covered = []
    for path in udev_rule_files(root):
        try:
            with open(path, errors="replace") as f:
                subsystems = rule_matches(f.read(), vid, pid)
        except OSError:
            continue
        if subsystems:
            shown = "/" + os.path.relpath(path, root)
            covered.append(f"`{shown}` ({', '.join(subsystems)})")
    return covered


# -- the report ---------------------------------------------------------------------------
def distribution(root):
    for rel in (("etc", "os-release"), ("usr", "lib", "os-release")):
        try:
            with open(_path(root, *rel)) as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.partition("=")[2].strip().strip('"')
        except OSError:
            continue
    return "unknown"


def table(rows):
    lines = ["| | |", "|---|---|"]
    lines += [f"| {key} | {value} |" for key, value in rows]
    return "\n".join(lines)


def environment_rows(root, quirks):
    experimental = os.environ.get(protocol.EXPERIMENTAL_ENV, "").strip()
    return [
        ("ragnaros", __version__),
        ("Python", platform.python_version()),
        ("kernel", platform.release()),
        ("distribution", distribution(root)),
        ("libusb-1.0", ctypes.util.find_library("usb-1.0") or "not found"),
        ("usbhid quirks", "unknown (usbhid not loaded?)" if quirks is None else
         ", ".join(f"`0x{v:04x}:0x{p:04x}:0x{f:08x}`" for v, p, f in quirks) or "none"),
        (f"`{protocol.EXPERIMENTAL_ENV}`", f"`{experimental}`" if experimental else "not set"),
    ]


def _endpoint_row(ep):
    address = ep["bEndpointAddress"] or "?"
    size = ep["wMaxPacketSize"]
    try:
        size = str(int(size, 16) & 0x7FF)
    except (TypeError, ValueError):
        size = "?"
    return (f"0x{address} {(ep['direction'] or '?').upper()}", ep["type"] or "?", size,
            f"{ep['interval'] or '?'} (bInterval {ep['bInterval'] or '?'})")


def device_section(root, directory, quirks):
    """(markdown, facts) for one device; facts feed the hints."""
    vid = int(read_attr(directory, "idVendor"), 16)
    pid = int(read_attr(directory, "idProduct"), 16)
    ident = f"{vid:04x}:{pid:04x}"
    product = read_attr(directory, "product")
    busnum, devnum = read_attr(directory, "busnum"), read_attr(directory, "devnum")
    try:
        node = f"/dev/bus/usb/{int(busnum):03d}/{int(devnum):03d}"
    except (TypeError, ValueError):
        node = None
    access = node_access(_path(root, node.lstrip("/"))) if node else None
    raw = read_bytes(os.path.join(directory, "descriptors")) or b""
    lengths = hid_descriptors(raw)
    intfs = interfaces(directory)
    experimental = os.environ.get(protocol.EXPERIMENTAL_ENV, "").strip()
    try:
        tried = vid == protocol.VID and experimental and protocol.parse_pid(experimental) == pid
    except ValueError:
        tried = False

    if (vid, pid) in SUPPORTED:
        status = f"Supported ({SUPPORTED[(vid, pid)]})."
    elif tried:
        status = (f"Not supported yet; `{protocol.EXPERIMENTAL_ENV}` opts it into "
                  "the experimental test.")
    else:
        status = "Not supported yet."
    quirk = [f for v, p, f in (quirks or []) if (v, p) == (vid, pid)]
    rules = udev_coverage(root, vid, pid)
    speed = read_attr(directory, "speed")
    rows = [
        ("manufacturer", read_attr(directory, "manufacturer") or "none"),
        ("product", product or "none"),
        # never read: only whether the device has one
        ("serial number", "present, not shown"
         if os.path.exists(os.path.join(directory, "serial")) else "none"),
        ("USB", f"{read_attr(directory, 'version') or '?'}, {speed or '?'} Mbit/s, "
                f"bcdDevice {read_attr(directory, 'bcdDevice') or '?'}, "
                f"class {read_attr(directory, 'bDeviceClass') or '?'}, "
                f"{read_attr(directory, 'bNumConfigurations') or '?'} configuration(s), "
                f"{(read_attr(directory, 'bNumInterfaces') or '?').strip()} interface(s), "
                f"{read_attr(directory, 'bMaxPower') or '?'}"),
        ("sysfs", f"`{os.path.basename(directory)}`"),
        ("device node", f"`{node}` {access}" if access else f"`{node}` (missing)"),
        ("usbhid quirk", ", ".join(
            f"`0x{f:08x}` ({QUIRK_NAMES.get(f, 'flags')})" for f in quirk) or "none"),
        ("udev rules", ", ".join(rules) or "none match"),
    ]
    out = [f"#### {ident} {product or ''}".rstrip(), "", status, "", table(rows), ""]

    out += ["| interface | class | driver | endpoint | type | max packet | interval |",
            "|---|---|---|---|---|---|---|"]
    for intf in intfs:
        klass = intf["class"] or "?"
        label = CLASSES.get(klass, "")
        boot = BOOT_PROTOCOLS.get((intf["subclass"], intf["protocol"]))
        label = f"{label}, {boot}" if boot and klass == "03" else label
        head = [str(int(intf["number"], 16)) if intf["number"] else "?",
                f"{klass}/{intf['subclass'] or '?'}/{intf['protocol'] or '?'}"
                + (f" {label}" if label else ""),
                intf["driver"] or "none"]
        eps = intf["endpoints"] or [None]
        for n, ep in enumerate(eps):
            cells = (head if n == 0 else ["", "", ""]) + \
                (list(_endpoint_row(ep)) if ep else ["none", "", "", ""])
            out.append("| " + " | ".join(cells) + " |")
    out.append("")

    for intf in intfs:
        number = int(intf["number"], 16) if intf["number"] else None
        declared = lengths.get(number)
        size = f" ({declared[1]} bytes declared, HID {declared[0]})" if declared else ""
        descriptors = [h for h in intf["hid"] if h["report_descriptor"]]
        if not descriptors:
            if intf["class"] == "03":
                why = (f"no HID driver bound (driver: {intf['driver'] or 'none'})"
                       if not intf["hid"] else "not readable")
                out += [f"HID report descriptor, interface {number}{size}: {why}.", ""]
            continue
        for hid in descriptors:
            nodes = []
            for name in hid["hidraw"]:
                hid_access = node_access(_path(root, "dev", name))
                nodes.append(f"`/dev/{name}` {hid_access}" if hid_access
                             else f"`/dev/{name}` (missing)")
            out += [f"HID report descriptor, interface {number}{size}"
                    + (f", {', '.join(nodes)}" if nodes else ""), "",
                    "```", hexdump(hid["report_descriptor"]), "```", ""]

    if raw:
        out += ["<details><summary>Raw USB descriptors "
                f"({len(raw)} bytes, as <code>lsusb -v</code> decodes them)</summary>", "",
                "```", hexdump(raw), "```", "", "</details>", ""]
    facts = {"id": ident, "vid": vid, "pid": pid, "node": node,
             "writable": bool(access and "read+write" in access),
             "supported": (vid, pid) in SUPPORTED}
    return "\n".join(out), facts


def hints(facts):
    """What to do next; printed on stderr so `> report.md` keeps only the report."""
    lines = []
    for fact in facts:
        if fact["supported"]:
            if not fact["writable"]:
                lines.append(f"{fact['id']}: you cannot open {fact['node']}; install the udev "
                             "rules (`ragnaros install-system` or the .deb/AUR package) and "
                             "reboot once.")
            continue
        if fact["vid"] != protocol.VID:
            continue
        lines.append(f"{fact['id']} is not supported yet. To try it with the SS552 protocol "
                     "(experimental; README, \"Reporting a new device\"):")
        steps = []
        if not fact["writable"] and fact["node"]:
            steps.append((f"sudo chown \"$USER\" {fact['node']}", "until you unplug it"))
        steps += [("systemctl --user stop ragnarosd", "if it runs"),
                  (f"ragnarosd --experimental-pid 0x{fact['pid']:04x}", "stays in the foreground"),
                  ("ragnarosctl watch --grab", "in a second terminal; press every key")]
        lines += [f"  {command:<40} # {note}" for command, note in steps]
    return lines


def report(root=None, device=None):
    """(markdown, hints, found): the report for vendor 0200, or one VID:PID."""
    root = ROOT if root is None else root
    vid, pid = device if device else (protocol.VID, None)
    quirks = usbhid_quirks(root)
    wanted = f"{vid:04x}:{pid:04x}" if pid is not None else f"vendor {vid:04x}"
    out = ["### Ragnaros device report", "", table(environment_rows(root, quirks)), ""]
    facts = []
    devices = find_devices(root, vid, pid)
    for directory in devices:
        text, fact = device_section(root, directory, quirks)
        out.append(text)
        facts.append(fact)
    if not devices:
        out += [f"No USB device found for {wanted}.", ""]
        notes = [f"No USB device found for {wanted}: is it plugged in? `lsusb` lists them"
                 + ("." if device else "; --device VID:PID reports another vendor's.")]
    else:
        notes = hints(facts)
    return "\n".join(out).rstrip() + "\n", notes, bool(devices)


def run(args):
    text, notes, found = report(device=args.device)
    sys.stdout.write(text)
    sys.stdout.flush()
    for line in notes:
        print(line, file=sys.stderr)
    return 0 if found else 1
