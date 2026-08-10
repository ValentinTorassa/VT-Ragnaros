from PIL import Image, ImageSequence


def load_icon(path, size):
    img = Image.open(path).convert("RGB")
    return img.resize(size, Image.LANCZOS)


def gif_frames(path, size):
    img = Image.open(path)
    for frame in ImageSequence.Iterator(img):
        frame = frame.convert("RGB").resize(size, Image.LANCZOS)
        duration = frame.info.get("duration", 100) / 1000
        yield frame, max(duration, 0.03)


def compose_strip(base, text=None, font_size=20):
    from PIL import ImageDraw

    img = base.copy()
    if text:
        draw = ImageDraw.Draw(img)
        draw.text((10, img.height - font_size - 8), text, fill=(255, 255, 255))
    return img


def blank(size, color=(0, 0, 0)):
    return Image.new("RGB", size, color)


def to_bytes(img):
    return img.tobytes()
