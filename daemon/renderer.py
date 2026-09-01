from PIL import Image, ImageDraw, ImageFont, ImageSequence

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


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


def fit_text(draw, text, max_width, base_size, font_path=FONT_BOLD):
    size = base_size
    while size > 10:
        font = ImageFont.truetype(font_path, size)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            break
        size -= 1
    return ImageFont.truetype(font_path, size)


def now_playing_strip(title, artist, position, length, size):
    """704x124 strip frame: title, artist, progress bar on pure black."""
    w, h = size
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((16, 14), "\u25b6", font=ImageFont.truetype(FONT_BOLD, 20), fill=(120, 220, 160))
    tfont = fit_text(d, title, w - 60, 30)
    d.text((46, 12), title, font=tfont, fill=(240, 240, 245))
    if artist:
        afont = fit_text(d, artist, w - 40, 18, FONT)
        d.text((18, 52), artist, font=afont, fill=(150, 155, 170))
    # progress bar
    frac = max(0.0, min(1.0, position / length)) if length else 0.0
    d.rectangle((16, h - 26, w - 16, h - 18), fill=(30, 32, 42))
    d.rectangle((16, h - 26, 16 + int((w - 32) * frac), h - 18), fill=(120, 200, 250))
    if length:
        def mmss(s):
            s = int(s)
            return f"{s // 60}:{s % 60:02d}"
        pfont = ImageFont.truetype(FONT, 13)
        d.text((16, h - 16), mmss(position), font=pfont, fill=(140, 145, 160))
        end = mmss(length)
        bb = d.textbbox((0, 0), end, font=pfont)
        d.text((w - 16 - (bb[2] - bb[0]), h - 16), end, font=pfont, fill=(140, 145, 160))
    return img


def state_tile(size, glyph_path, caption, accent, glyph_fill=(255, 255, 255),
               bg=(16, 17, 21), border=None):
    """Dynamic dark tile: image glyph at top (or None), caption below in accent."""
    img = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(img)
    if border:
        d.rectangle((0, 0, size - 1, size - 1), outline=border, width=4)
    cy = size // 2 - 14
    if glyph_path:
        try:
            icon = Image.open(glyph_path).convert("RGBA")
            icon.thumbnail((int(size * 0.78), int(size * 0.78)), Image.LANCZOS)
            img.paste(icon, ((size - icon.width) // 2, cy - icon.height // 2), icon)
        except OSError:
            pass
    else:
        cfont = fit_text(d, caption, size - 16, 26)
        bbox = d.textbbox((0, 0), caption, font=cfont)
        d.text(((size - bbox[2]) / 2, cy - (bbox[3] - bbox[1]) / 2 - bbox[1]),
               caption, font=cfont, fill=glyph_fill)
        return img
    font = fit_text(d, caption, size - 12, 15)
    bbox = d.textbbox((0, 0), caption, font=font)
    d.text(((size - bbox[2]) / 2, size - 30), caption, font=font, fill=accent)
    return img
