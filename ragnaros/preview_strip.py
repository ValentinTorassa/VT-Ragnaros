"""Render the strip frames to a PNG so the layout can be judged without the deck.

Usage: ragnaros-preview-strip [out.png]

Red lines mark the bezels between the four 176x124 panels: no glyph and
no bar may cross one.
"""
import sys

from PIL import Image, ImageDraw

from . import renderer

STRIP = (704, 124)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    out = argv[0] if argv else "strip_preview.png"

    art = Image.new("RGB", (600, 400), (90, 30, 110))
    d = ImageDraw.Draw(art)
    d.ellipse((150, 50, 450, 350), fill=(230, 180, 60))

    frames = [
        renderer.now_playing_strip("Numb", "Linkin Park", 84, 186, STRIP, art),
        renderer.now_playing_strip("Everything In Its Right Place", "Radiohead",
                                   150, 251, STRIP, art),
        renderer.now_playing_strip("Bohemian Rhapsody", "Queen", 45, 355, STRIP),
        renderer.overlay_strip("VOLUME", 0.37, STRIP),
        renderer.overlay_strip("BRIGHTNESS", 0.85, STRIP),
    ]

    sheet = Image.new("RGB", (STRIP[0], len(frames) * (STRIP[1] + 8) - 8), (60, 60, 60))
    for i, frame in enumerate(frames):
        mark = ImageDraw.Draw(frame)
        for seam in (176, 352, 528):
            mark.line((seam, 0, seam, STRIP[1]), fill=(255, 0, 0))
        sheet.paste(frame, (0, i * (STRIP[1] + 8)))
    sheet.save(out)
    print(f"{out}: {len(frames)} frames")
    return 0


if __name__ == "__main__":
    sys.exit(main())
