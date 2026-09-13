#!/usr/bin/env python3
"""Find out what the firmware's MOD command does.

protocol.set_mode() sends CRT + "MOD" + ('0' + n). It was decoded from the
vendor DLL and never called: nobody knows what the modes are. This paints a
readable pattern, then walks the modes so you can watch the deck and say what
changed.

    systemctl --user stop ragnarosd
    python3 tools/probe_modes.py            # sweep 0-9, 5 s each
    python3 tools/probe_modes.py 3          # just mode 3, then restore
    systemctl --user start ragnarosd

Besides the pattern, every step dumps the device's feature and input
reports, so a mode that flips firmware state shows up in the diff even
with nobody watching the panels.

If the deck ends up wedged, ~/.local/bin/ragnaros-reset puts it back.
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))

from PIL import Image, ImageDraw, ImageFont

from protocol import KEY_COUNT, KEY_LCD, ROTATION, STRIP_LCD, Ragnaros

HOLD = float(os.environ.get("RAGNAROS_PROBE_HOLD", "5"))
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size):
    try:
        return ImageFont.truetype(SANS, size)
    except OSError:
        return ImageFont.load_default(size)


def jpeg(img):
    buf = io.BytesIO()
    img.rotate(ROTATION).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def key_tile(label, color):
    img = Image.new("RGB", KEY_LCD, (14, 15, 19))
    d = ImageDraw.Draw(img)
    f = font(46)
    bb = d.textbbox((0, 0), label, font=f)
    d.text(((KEY_LCD[0] - bb[2]) / 2, (KEY_LCD[1] - bb[3]) / 2 - bb[1] / 2),
           label, font=f, fill=color)
    return jpeg(img)


def strip_tile(text, color):
    img = Image.new("RGB", STRIP_LCD, (10, 10, 14))
    d = ImageDraw.Draw(img)
    f = font(34)
    bb = d.textbbox((0, 0), text, font=f)
    d.text(((STRIP_LCD[0] - bb[2]) / 2, (STRIP_LCD[1] - bb[3]) / 2 - bb[1] / 2),
           text, font=f, fill=color)
    return jpeg(img)


def paint(deck, caption):
    palette = [(240, 90, 90), (240, 170, 70), (240, 230, 90), (140, 230, 120),
               (110, 220, 230), (120, 160, 250), (180, 130, 250), (250, 130, 200),
               (230, 230, 235), (150, 150, 160)]
    for key in range(KEY_COUNT):
        deck.send_image(key, key_tile(str(key), palette[key]))
    deck.flush()
    for seg in range(4):
        deck.send_image(seg, strip_tile(caption[seg] if seg < len(caption) else "",
                                        (120, 200, 250)), strip=True)
        deck.flush()


def snapshot(deck):
    """Feature + input reports, so state changes are visible without eyes."""
    state = {}
    for report in range(4):
        try:
            state[f"feature{report}"] = deck.get_feature_report(report, 32).hex(" ")
        except RuntimeError as error:
            state[f"feature{report}"] = f"error: {error}"
    try:
        state["input1"] = deck.get_input_report(1, 32).hex(" ")
    except RuntimeError as error:
        state["input1"] = f"error: {error}"
    return state


def diff(before, after):
    return [f"    {key}: {before[key]}  ->  {after[key]}"
            for key in after if before.get(key) != after[key]]


def main():
    modes = [int(sys.argv[1])] if len(sys.argv) > 1 else list(range(10))
    deck = Ragnaros()
    try:
        deck.initialize()
        deck.set_brightness(100)
        paint(deck, ["MODE", "PROBE", "WATCH", "THE DECK"])
        print("pattern painted: keys 0-9 in colour, strip reading MODE PROBE.")
        print("note what changes at each step - layout, brightness, colours, input.\n")
        time.sleep(2)
        baseline = snapshot(deck)
        print("baseline reports:")
        for key, value in baseline.items():
            print(f"    {key}: {value}")
        print()
        previous = baseline
        for mode in modes:
            print(f"  -> set_mode({mode})   [CRT MOD {chr(0x30 + mode)!r}]", flush=True)
            deck.set_mode(mode)
            paint(deck, ["MODE", str(mode), "", ""])
            time.sleep(HOLD)
            current = snapshot(deck)
            changes = diff(previous, current)
            print("\n".join(changes) if changes else "    (reports unchanged)")
            # does the deck still take input after this mode?
            event = deck.poll(200)
            if event:
                print(f"    unsolicited input: {event}")
            previous = current
    finally:
        print("\nrestoring mode 0 and repainting")
        try:
            deck.set_mode(0)
            deck.reset_display()
            paint(deck, ["DONE", "START", "THE", "DAEMON"])
        except Exception as error:
            print(f"restore failed ({error}); run ~/.local/bin/ragnaros-reset",
                  file=sys.stderr)
        deck.close()
    print("done - now: systemctl --user start ragnarosd")


if __name__ == "__main__":
    main()
