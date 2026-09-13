import dbuswatch

TRANSCRIPT = """method call time=1 sender=:1.4 -> destination=:1.7 serial=9 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify
   string "Signal"
   uint32 0
   string ""
   string "Mensaje nuevo"
   string "nos vemos a las 8"
   array [
   ]
   array [
      dict entry(
         string "urgency"
         variant             byte 1
      )
   ]
   int32 -1
signal time=2 sender=:1.9 -> destination=(null destination) path=/org/gnome/ScreenSaver; interface=org.gnome.ScreenSaver; member=ActiveChanged
   boolean true
signal time=3 sender=:1.9 -> destination=(null destination) path=/org/gnome/ScreenSaver; interface=org.gnome.ScreenSaver; member=ActiveChanged
   boolean false
"""


class FakeProc:
    def __init__(self, text):
        self.stdout = iter(text.splitlines(keepends=True))


def watcher(text):
    watch = dbuswatch.DBusWatch.__new__(dbuswatch.DBusWatch)
    import queue

    watch.events = queue.Queue(maxsize=64)
    watch.proc = FakeProc(text)
    watch._pump()
    return list(watch.drain(budget=16))


def test_parses_notifications_and_lock_state():
    assert watcher(TRANSCRIPT) == [
        ("notify", {"app": "Signal", "summary": "Mensaje nuevo",
                    "body": "nos vemos a las 8"}),
        ("lock", True),
        ("lock", False),
    ]


def test_login1_lock_signals_are_understood():
    events = watcher(
        "signal time=4 sender=:1.2 path=/org/freedesktop/login1/session/_32; "
        "interface=org.freedesktop.login1.Session; member=Lock\n")
    assert events == [("lock", True)]


def test_quotes_in_a_notification_survive():
    text = TRANSCRIPT.replace('"Mensaje nuevo"', r'"dijo \"hola\""')
    assert watcher(text)[0][1]["summary"] == 'dijo "hola"'
