"""Convert any GIF to the Ragnaros strip format (704x124):
sharp subject centered over a blurred full-scene background.

Usage: ragnaros-strip-gif in.gif out.gif [duration_ms]

Name the result in a profile as strip.gif (one GIF across all four panels),
from any assets root, e.g. ~/.local/share/ragnaros/gifs/mine.gif -> gifs/mine.gif.
"""
import sys

from PIL import Image, ImageFilter, ImageSequence

W, H = 704, 124


def convert(src_path, dst_path, duration=90):
    src = Image.open(src_path)
    frames = []
    for f in ImageSequence.Iterator(src):
        f = f.convert("RGB")
        # background: cover the strip, blurred
        scale = max(W / f.width, H / f.height)
        bg = f.resize((int(f.width * scale) + 1, int(f.height * scale) + 1), Image.LANCZOS)
        x = (bg.width - W) // 2
        y = (bg.height - H) // 2
        bg = bg.crop((x, y, x + W, y + H)).filter(ImageFilter.GaussianBlur(6))
        # foreground: fit height, centered
        fg = f.resize((int(f.width * H / f.height), H), Image.LANCZOS)
        if fg.width > W:
            x = (fg.width - W) // 2
            fg = fg.crop((x, 0, x + W, H))
        bg.paste(fg, ((W - fg.width) // 2, 0))
        frames.append(bg)
    frames[0].save(dst_path, save_all=True, append_images=frames[1:],
                   duration=duration, loop=0, optimize=True)
    print(f"{dst_path}: {len(frames)} frames")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    convert(argv[0], argv[1], int(argv[2]) if len(argv) > 2 else 90)
    return 0


if __name__ == "__main__":
    sys.exit(main())
