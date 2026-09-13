"""Desktop events for the deck: notifications and screen lock.

dbus-monitor is the only way to see notifications - Notify is a method
call on the session bus, not a signal, so gdbus monitor cannot see it.
The output is parsed in a thread and handed to the main loop as events;
if dbus-monitor is missing the watcher stays quiet instead of failing.
"""
import queue
import re
import shutil
import subprocess
import sys
import threading

STRING = re.compile(r'^   string "(.*)"$')
BOOLEAN = re.compile(r"^   boolean (true|false)$")

RULES = (
    "interface='org.freedesktop.Notifications',member='Notify'",
    "type='signal',interface='org.gnome.ScreenSaver',member='ActiveChanged'",
    "type='signal',interface='org.freedesktop.login1.Session'",
)


def unescape(text):
    return text.replace('\\"', '"').replace("\\\\", "\\")


class DBusWatch:
    """Yields ("notify", {...}) and ("lock", bool) events."""

    def __init__(self, rules=RULES):
        self.events = queue.Queue(maxsize=64)
        self.proc = None
        if not shutil.which("dbus-monitor"):
            print("ragnaros: dbus-monitor not found, desktop events disabled",
                  file=sys.stderr)
            return
        try:
            self.proc = subprocess.Popen(
                ["dbus-monitor", "--session", *rules],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError as error:
            print(f"ragnaros: dbus-monitor failed to start: {error}", file=sys.stderr)
            return
        threading.Thread(target=self._pump, daemon=True).start()

    def _emit(self, event):
        try:
            self.events.put_nowait(event)
        except queue.Full:
            pass

    def _pump(self):
        kind, strings = None, []
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            if line.startswith(("method call", "signal", "method return", "error")):
                if kind == "notify" and len(strings) >= 4:
                    self._emit(("notify", {"app": strings[0], "summary": strings[2],
                                           "body": strings[3]}))
                kind, strings = None, []
                if "member=Notify" in line:
                    kind = "notify"
                elif "member=ActiveChanged" in line:
                    kind = "lock"
                elif "member=Lock" in line:
                    self._emit(("lock", True))
                elif "member=Unlock" in line:
                    self._emit(("lock", False))
                continue
            if kind == "notify":
                match = STRING.match(line)
                if match:
                    strings.append(unescape(match.group(1)).split("\n")[0])
                elif line.startswith("   array"):
                    if len(strings) >= 4:
                        self._emit(("notify", {"app": strings[0], "summary": strings[2],
                                               "body": strings[3]}))
                    kind, strings = None, []
            elif kind == "lock":
                match = BOOLEAN.match(line)
                if match:
                    self._emit(("lock", match.group(1) == "true"))
                    kind = None

    def drain(self, budget=8):
        for _ in range(budget):
            try:
                yield self.events.get_nowait()
            except queue.Empty:
                return

    def close(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None
