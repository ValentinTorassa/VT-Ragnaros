"""System metrics for the strip dashboard.

Every provider reads /proc and /sys directly - no subprocesses, so the
dashboard costs nothing next to the USB writes. A provider returns a
card dict for renderer.cards_strip, or None when the machine has no
such sensor (a desktop without a battery, a kernel without hwmon).
"""
import os
import time

ACCENT = (120, 200, 250)
WARM = (250, 190, 90)
HOT = (250, 110, 110)
COOL = (140, 230, 170)


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _level(frac, warm=0.7, hot=0.9):
    return HOT if frac >= hot else WARM if frac >= warm else COOL


class Metrics:
    """Keeps the previous counter sample so rates can be derived."""

    def __init__(self):
        self._cpu = None
        self._net = None

    # -- providers ----------------------------------------------------------
    def clock(self):
        now = time.localtime()
        return {"label": time.strftime("%a %d %b", now).upper(),
                "value": time.strftime("%H:%M", now),
                "sub": time.strftime("week %V", now)}

    def cpu(self):
        fields = _read("/proc/stat").split("\n")[0].split()[1:]
        if not fields:
            return None
        values = [int(v) for v in fields[:8]]
        busy, total = sum(values) - values[3] - values[4], sum(values)
        previous, self._cpu = self._cpu, (busy, total)
        if not previous:
            return {"label": "CPU", "value": "--", "sub": ""}
        d_busy, d_total = busy - previous[0], total - previous[1]
        frac = d_busy / d_total if d_total > 0 else 0.0
        load = _read("/proc/loadavg").split()[:1]
        return {"label": "CPU", "value": f"{frac * 100:.0f}%", "bar": frac,
                "accent": _level(frac), "sub": f"load {load[0]}" if load else ""}

    def ram(self):
        info = {}
        for line in _read("/proc/meminfo").splitlines():
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0]) if rest.split() else 0
        total, available = info.get("MemTotal", 0), info.get("MemAvailable", 0)
        if not total:
            return None
        used = total - available
        frac = used / total
        return {"label": "RAM", "value": f"{frac * 100:.0f}%", "bar": frac,
                "accent": _level(frac),
                "sub": f"{used / 1048576:.1f}/{total / 1048576:.0f} GB"}

    def _hwmon(self, chips):
        """Hottest temp*_input among the first matching hwmon chip."""
        base = "/sys/class/hwmon"
        if not os.path.isdir(base):
            return None
        found = {}
        for entry in sorted(os.listdir(base)):
            name = _read(f"{base}/{entry}/name")
            if name not in chips:
                continue
            for sensor in sorted(os.listdir(f"{base}/{entry}")):
                if not (sensor.startswith("temp") and sensor.endswith("_input")):
                    continue
                raw = _read(f"{base}/{entry}/{sensor}")
                if not raw.lstrip("-").isdigit():
                    continue
                label = _read(f"{base}/{entry}/{sensor[:-6]}_label") or name
                celsius = int(raw) / 1000
                if celsius > found.get(name, (0, ""))[0]:
                    found[name] = (celsius, label)
        for chip in chips:
            if chip in found:
                return found[chip]
        return None

    def temp(self):
        reading = self._hwmon(HWMON_CPU) or self._hwmon(("acpitz",))
        if reading is None:
            return None
        celsius, label = reading
        frac = max(0.0, min(1.0, (celsius - 30) / 60))
        return {"label": "CPU TEMP", "value": f"{celsius:.0f}°", "bar": frac,
                "accent": _level(frac, 0.66, 0.83), "sub": label[:14]}

    def gpu(self):
        reading = self._hwmon(HWMON_GPU)
        if reading is None:
            return None
        celsius, label = reading
        frac = max(0.0, min(1.0, (celsius - 30) / 60))
        return {"label": "GPU", "value": f"{celsius:.0f}°", "bar": frac,
                "accent": _level(frac, 0.66, 0.83), "sub": label[:14]}

    def disk(self, path="/"):
        try:
            st = os.statvfs(path)
        except OSError:
            return None
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if not total:
            return None
        frac = 1 - free / total
        return {"label": "DISK", "value": f"{frac * 100:.0f}%", "bar": frac,
                "accent": _level(frac, 0.8, 0.92),
                "sub": f"{free / 1e9:.0f} GB free"}

    def net(self):
        rx = tx = 0
        for line in _read("/proc/net/dev").splitlines()[2:]:
            name, _, rest = line.partition(":")
            if name.strip() in ("lo", ""):
                continue
            fields = rest.split()
            if len(fields) >= 9:
                rx += int(fields[0])
                tx += int(fields[8])
        now = time.monotonic()
        previous, self._net = self._net, (rx, tx, now)
        if not previous or now <= previous[2]:
            return {"label": "NET", "value": "--", "sub": ""}
        span = now - previous[2]
        down, up = (rx - previous[0]) / span, (tx - previous[1]) / span

        def rate(value):
            return f"{value / 1e6:.1f}M" if value >= 1e6 else f"{value / 1e3:.0f}K"

        return {"label": "NET", "value": f"↓{rate(down)}", "accent": ACCENT,
                "sub": f"↑{rate(up)}/s"}

    def battery(self):
        base = "/sys/class/power_supply"
        for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if not name.startswith("BAT"):
                continue
            capacity = _read(f"{base}/{name}/capacity")
            if not capacity.isdigit():
                continue
            frac = int(capacity) / 100
            status = _read(f"{base}/{name}/status") or "?"
            return {"label": "BATTERY", "value": f"{capacity}%", "bar": frac,
                    "accent": COOL if frac > 0.3 or status == "Charging" else HOT,
                    "sub": status.lower()}
        return None

    def uptime(self):
        raw = _read("/proc/uptime").split()
        if not raw:
            return None
        seconds = int(float(raw[0]))
        days, rest = divmod(seconds, 86400)
        hours, minutes = divmod(rest // 60, 60)
        value = f"{days}d {hours}h" if days else f"{hours}h {minutes:02d}m"
        return {"label": "UPTIME", "value": value, "sub": ""}

    # -- registry -----------------------------------------------------------
    def card(self, name):
        provider = getattr(self, name, None) if name in PROVIDERS else None
        if provider is None:
            return {"label": name.upper()[:10], "value": "?", "sub": "unknown"}
        try:
            return provider() or {"label": name.upper(), "value": "--", "sub": "n/a"}
        except Exception:
            return {"label": name.upper(), "value": "--", "sub": "error"}

    def cards(self, names):
        return [self.card(name) for name in list(names)[:4]]


HWMON_CPU = ("k10temp", "coretemp", "zenpower", "cpu_thermal")
HWMON_GPU = ("amdgpu", "nvidia", "radeon", "i915")
PROVIDERS = ("clock", "cpu", "ram", "temp", "gpu", "disk", "net", "battery", "uptime")
DEFAULT_DASHBOARD = ("clock", "cpu", "ram", "temp")
