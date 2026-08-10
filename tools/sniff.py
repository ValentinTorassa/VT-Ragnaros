#!/usr/bin/env python3
import os
import selectors
import sys
import time

VENDOR = "/dev/hidraw7"
KBD = "/dev/hidraw8"
SIZES = {VENDOR: 512, KBD: 8}


def main():
    fds = {}
    sel = selectors.DefaultSelector()
    for path in (VENDOR, KBD):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            print(f"cannot open {path}: {e}", file=sys.stderr)
            continue
        fds[fd] = path
        sel.register(fd, selectors.EVENT_READ)
    if not fds:
        sys.exit("no devices opened - install the udev rule first")
    print("sniffing: press keys and turn knobs (Ctrl+C to stop)")
    t0 = time.monotonic()
    while True:
        for key, _ in sel.select():
            fd = key.fd
            try:
                data = os.read(fd, SIZES[fds[fd]])
            except BlockingIOError:
                continue
            if not data:
                continue
            tag = "vendor" if fds[fd] == VENDOR else "kbd   "
            print(f"{time.monotonic()-t0:8.3f} {tag} {len(data):4d}B {data.hex(' ')}")


if __name__ == "__main__":
    main()
