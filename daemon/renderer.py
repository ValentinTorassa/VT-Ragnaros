from PIL import Image, ImageSequence


def load_icon(path, size, rotation=0):
    img = Image.open(path).convert("RGB").resize(size, Image.LANCZOS)
    return img.rotate(rotation) if rotation else img


def gif_frames(path, size, rotation=0):
    img = Image.open(path)
    for frame in ImageSequence.Iterator(img):
        frame = frame.convert("RGB").resize(size, Image.LANCZOS)
        if rotation:
            frame = frame.rotate(rotation)
        duration = frame.info.get("duration", 100) / 1000
        yield frame, max(duration, 0.03)


def to_jpeg(img, quality=90):
    import io

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


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
