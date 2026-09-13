#!/usr/bin/env python3
"""Paint 1 2 3 4 on the strip to reveal the physical order of slots 0-3.

Wide strip frames (now playing, knob overlays) are split into four
176x124 crops, so the daemon has to know whether slot 0 is the leftmost
or the rightmost panel. Stop the daemon first:

    systemctl --user stop ragnarosd
    python3 tools/strip_order.py
    systemctl --user start ragnarosd

Read the strip: "1 2 3 4" means slot 0 is on the left, "4 3 2 1" means
slot 0 is on the right (which is what push_strip_frame assumes today).
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))

from PIL import Image, ImageDraw, ImageFont

from protocol import ROTATION, STRIP_LCD, Ragnaros

COLORS = [(230, 60, 70), (60, 180, 90), (60, 140, 240), (240, 190, 60)]


def make_jpeg(slot):
    img = Image.new("RGB", STRIP_LCD, (12, 12, 16))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
    except OSError:
        font = ImageFont.load_default(80)
    label = str(slot + 1)
    bb = d.textbbox((0, 0), label, font=font)
    d.text(((STRIP_LCD[0] - bb[2]) / 2, (STRIP_LCD[1] - bb[3]) / 2 - bb[1] / 2),
           label, font=font, fill=COLORS[slot])
    buf = io.BytesIO()
    img.rotate(ROTATION).save(buf, "JPEG", quality=90)
    return buf.getvalue()


deck = Ragnaros()
deck.initialize()
for slot in range(4):
    deck.send_image(slot, make_jpeg(slot), strip=True)
    deck.flush()
print("painted slots 0-3 as 1 2 3 4 - read the strip left to right")
for _ in range(30):  # hold the picture against the firmware watchdog
    deck.keep_alive()
    time.sleep(1)
deck.close()
