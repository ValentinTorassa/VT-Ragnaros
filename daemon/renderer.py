from PIL import Image, ImageDraw, ImageFont, ImageSequence

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


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


def fit_text(draw, text, max_width, base_size, font_path=FONT_BOLD):
    size = base_size
    while size > 10:
        font = load_font(font_path, size)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            break
        size -= 1
    return load_font(font_path, size)


def cover_crop(img, size):
    """Scale to cover the box and center-crop: no squash, no black bands."""
    w, h = size
    scale = max(w / img.width, h / img.height)
    scaled = img.resize((max(w, round(img.width * scale)),
                         max(h, round(img.height * scale))), Image.LANCZOS)
    x, y = (scaled.width - w) // 2, (scaled.height - h) // 2
    return scaled.crop((x, y, x + w, y + h))


def wrap_text(draw, text, font, max_width):
    """Word-wrap, hard-breaking any single word wider than the box."""
    lines, line = [], ""
    for word in text.split():
        while draw.textlength(word, font=font) > max_width and len(word) > 1:
            cut = len(word) - 1
            while cut > 1 and draw.textlength(word[:cut], font=font) > max_width:
                cut -= 1
            if line:
                lines.append(line)
                line = ""
            lines.append(word[:cut])
            word = word[cut:]
        trial = f"{line} {word}".strip()
        if not line or draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit_block(draw, text, box, max_size, font_path=FONT_BOLD, max_lines=3, min_size=12):
    """Biggest font at which text wraps into box within max_lines."""
    w, h = box
    font = load_font(font_path, min_size)
    lines = wrap_text(draw, text, font, w)
    for size in range(max_size, min_size - 1, -1):
        candidate = load_font(font_path, size)
        wrapped = wrap_text(draw, text, candidate, w)
        if len(wrapped) <= max_lines and len(wrapped) * (size + 5) <= h:
            return candidate, wrapped
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "\u2026"
    return font, lines


def draw_block(draw, lines, font, cell, fill):
    """Center a wrapped block inside cell=(x, y, w, h)."""
    x, y, w, h = cell
    step = font.size + 5
    top = y + (h - len(lines) * step) / 2
    for i, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        draw.text((x + (w - width) / 2, top + i * step), line, font=font, fill=fill)


def mmss(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def now_playing_strip(title, artist, position, length, size, art=None):
    """704x124 strip frame laid out as four self-contained 176x124 cards.

    The strip is four separate panels with bezels between them, so
    nothing may cross a cell boundary: album art fills card 0, the title
    and artist get a card each, and the progress bar lives inside card 3.
    """
    w, h = size
    cw = w // 4
    pad = 12
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)

    # card 0: cover art, edge to edge
    if art is not None:
        img.paste(cover_crop(art.convert("RGB"), (cw, h)), (0, 0))
    else:
        d.rectangle((0, 0, cw - 1, h - 1), fill=(14, 15, 19))
        glyph = load_font(FONT_BOLD, 54)
        bb = d.textbbox((0, 0), "\u25b6", font=glyph)
        d.text(((cw - bb[2]) / 2, (h - bb[3]) / 2 - bb[1] / 2), "\u25b6",
               font=glyph, fill=(120, 220, 160))

    # card 1: title
    box = (cw - 2 * pad, h - 2 * pad)
    font, lines = fit_block(d, title or "", box, 32)
    draw_block(d, lines, font, (cw + pad, pad, box[0], box[1]), (240, 240, 245))

    # card 2: artist
    if artist:
        font, lines = fit_block(d, artist, box, 24, FONT)
        draw_block(d, lines, font, (2 * cw + pad, pad, box[0], box[1]), (150, 155, 170))

    # card 3: elapsed over a contained bar over total
    x0, x1 = 3 * cw + pad + 4, 4 * cw - pad - 4
    if length:
        frac = max(0.0, min(1.0, position / length))
        top, bot = h // 2 - 5, h // 2 + 5
        d.rounded_rectangle((x0, top, x1, bot), radius=5, fill=(30, 32, 42))
        filled = x0 + (x1 - x0) * frac
        if filled > x0 + 1:
            d.rounded_rectangle((x0, top, filled, bot), radius=5, fill=(120, 200, 250))
        elapsed_font, total_font = load_font(FONT_BOLD, 26), load_font(FONT, 20)
        elapsed, total = mmss(position), mmss(length)
        d.text((x0 + (x1 - x0 - d.textlength(elapsed, font=elapsed_font)) / 2, top - 44),
               elapsed, font=elapsed_font, fill=(235, 238, 245))
        d.text((x0 + (x1 - x0 - d.textlength(total, font=total_font)) / 2, bot + 14),
               total, font=total_font, fill=(140, 145, 160))
    else:
        font = load_font(FONT_BOLD, 26)
        label = mmss(position)
        d.text((x0 + (x1 - x0 - d.textlength(label, font=font)) / 2, h / 2 - 18),
               label, font=font, fill=(235, 238, 245))
    return img


def alert_strip(app, summary, body, waited, size, pulse=False):
    """A notice that stays up until it is acknowledged.

    Same card grid as everything else; the last card counts how long it
    has been waiting, which is the part you actually read from across
    the room.
    """
    accent = (250, 210, 120) if pulse else (250, 170, 70)
    if waited < 60:
        waited_text, unit = f"{int(waited)}", "segundos"
    elif waited < 3600:
        waited_text, unit = f"{int(waited // 60)}m", "minutos esperando"
    else:
        waited_text, unit = f"{int(waited // 3600)}h", "horas esperando"
    return cards_strip([
        {"label": "", "value": (app or "aviso")[:14], "accent": accent, "sub": ""},
        {"label": "", "value": summary or "", "sub": "", "lines": 3, "size": 24},
        {"label": "", "value": body or "", "sub": "", "lines": 4, "size": 17,
         "font": FONT, "accent": (185, 190, 205)},
        {"label": "", "value": waited_text, "accent": accent, "sub": unit},
    ], size)


def cards_strip(cards, size):
    """Four independent info cards: label on top, big value, optional bar, sub.

    Same grid as now_playing_strip - nothing crosses a panel bezel.
    """
    w, h = size
    cw = w // 4
    pad = 12
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, card in enumerate(list(cards)[:4]):
        if not card:
            continue
        x = i * cw
        inner = cw - 2 * pad
        accent = card.get("accent") or (235, 238, 245)
        label = str(card.get("label") or "")
        if label:
            font, lines = fit_block(d, label, (inner, 20), 15, FONT, max_lines=1)
            draw_block(d, lines, font, (x + pad, 8, inner, 20), (125, 130, 148))
        value = str(card.get("value") or "")
        rows = int(card.get("lines", 1))
        top, height = (32, 46) if rows == 1 else (16, 86)
        font, lines = fit_block(d, value, (inner, height), int(card.get("size", 42)),
                                card.get("font", FONT_BOLD), max_lines=rows)
        draw_block(d, lines, font, (x + pad, top, inner, height), accent)
        if card.get("bar") is not None:
            frac = max(0.0, min(1.0, float(card["bar"])))
            x0, x1 = x + pad + 6, x + cw - pad - 6
            top, bot = h - 38, h - 30
            d.rounded_rectangle((x0, top, x1, bot), radius=4, fill=(30, 32, 42))
            filled = x0 + (x1 - x0) * frac
            if filled >= x0 + 8:
                d.rounded_rectangle((x0, top, filled, bot), radius=4, fill=accent)
        sub = str(card.get("sub") or "")
        if sub:
            font, lines = fit_block(d, sub, (inner, 18), 13, FONT, max_lines=1)
            draw_block(d, lines, font, (x + pad, h - 24, inner, 18), (140, 145, 160))
    return img


def toast_strip(app, summary, body, size, accent=(120, 200, 250)):
    """A desktop notification on the card grid: app, summary, body, clock."""
    import time as _time

    return cards_strip([
        {"label": "", "value": (app or "notice")[:14], "accent": accent, "sub": ""},
        {"label": "", "value": summary or "", "sub": "", "lines": 3, "size": 24},
        {"label": "", "value": body or "", "sub": "", "lines": 4, "size": 17,
         "font": FONT, "accent": (185, 190, 205)},
        {"label": _time.strftime("%a %d"), "value": _time.strftime("%H:%M"), "sub": ""},
    ], size)


def overlay_strip(label, frac, size):
    """704x124 knob feedback frame on the same four-card grid.

    The level reads as one meter but is drawn as four contained chunks,
    so the panel bezels fall in the gaps instead of cutting the bar.
    """
    w, h = size
    cw = w // 4
    pad = 12
    frac = max(0.0, min(1.0, frac))
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    box = (cw - 2 * pad, h // 2)
    font, lines = fit_block(d, label, box, 30, max_lines=1)
    draw_block(d, lines, font, (pad, 4, box[0], box[1]), (240, 240, 245))
    pct = f"{int(round(frac * 100))}%"
    font, lines = fit_block(d, pct, box, 34, max_lines=1)
    draw_block(d, lines, font, (3 * cw + pad, 4, box[0], box[1]), (120, 200, 250))
    top, bot = h - 54, h - 26
    radius = 10
    for seg in range(4):
        x0, x1 = seg * cw + pad + 4, (seg + 1) * cw - pad - 4
        d.rounded_rectangle((x0, top, x1, bot), radius=radius, fill=(30, 32, 42))
        filled = x0 + (x1 - x0) * min(1.0, max(0.0, frac * 4 - seg))
        if filled >= x0 + 2 * radius:
            d.rounded_rectangle((x0, top, filled, bot), radius=radius,
                                fill=(120, 200, 250))
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
