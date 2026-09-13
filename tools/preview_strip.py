#!/usr/bin/env python3
"""Render the strip frames to a PNG so the layout can be judged without the deck.

Usage: python3 tools/preview_strip.py [out.png]

Red lines mark the bezels between the four 176x124 panels: no glyph and
no bar may cross one.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))

from PIL import Image, ImageDraw

import renderer

STRIP = (704, 124)
OUT = sys.argv[1] if len(sys.argv) > 1 else "strip_preview.png"

art = Image.new("RGB", (600, 400), (90, 30, 110))
d = ImageDraw.Draw(art)
d.ellipse((150, 50, 450, 350), fill=(230, 180, 60))

FRAMES = [
    renderer.now_playing_strip("Numb", "Linkin Park", 84, 186, STRIP, art),
    renderer.now_playing_strip("Everything In Its Right Place", "Radiohead",
                               150, 251, STRIP, art),
    renderer.now_playing_strip("Bohemian Rhapsody", "Queen", 45, 355, STRIP),
    renderer.overlay_strip("VOLUME", 0.37, STRIP),
    renderer.overlay_strip("BRIGHTNESS", 0.85, STRIP),
]

sheet = Image.new("RGB", (STRIP[0], len(FRAMES) * (STRIP[1] + 8) - 8), (60, 60, 60))
for i, frame in enumerate(FRAMES):
    mark = ImageDraw.Draw(frame)
    for seam in (176, 352, 528):
        mark.line((seam, 0, seam, STRIP[1]), fill=(255, 0, 0))
    sheet.paste(frame, (0, i * (STRIP[1] + 8)))
sheet.save(OUT)
print(f"{OUT}: {len(FRAMES)} frames")
