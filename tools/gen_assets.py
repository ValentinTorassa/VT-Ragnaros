#!/usr/bin/env python3
"""Generate Ragnaros key icons (112x112) in one unified dark style:
real app icons where available, white FA glyphs with accent captions elsewhere.

Usage: python3 tools/gen_assets.py [outdir]   (default: repo assets/)
"""
import colorsys
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "assets")
ICON_DIR = os.path.join(OUT, "icons")

SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FA = os.path.join(OUT, "fonts", "fa-solid-900.ttf")
TILE = 112
DARK_TOP = (38, 40, 48)
DARK_BOT = (16, 17, 21)

# system actions: name -> (FA glyph codepoint, caption, accent RGB)
ICONS = {
    "mic_mute":     (0xF131, "MIC",    (240, 110, 200)),
    "folder":       (0xF07B, "FILES",  (120, 170, 250)),
    "lock":         (0xF023, "LOCK",   (170, 170, 185)),
    "chatgpt":      (0xF086, "GPT",    (120, 250, 190)),
    "tmux":         (0xF0DB, "TMUX",   ( 95, 215,  95)),
    "switch_ai":    (0xF544, "AI",     ( 60, 230, 230)),
    "switch_stream":(0xF26C, "HOME",   (140, 160, 250)),
    # legacy/extra tiles
    "obs_live":     (0xF519, "LIVE",   (245,  90,  90)),
    "obs_stop":     (0xF04D, "STOP",   (160, 160, 170)),
    "obs_record":   (0xF111, "REC",    (245,  80,  80)),
    "scene_main":   (0xF108, "MAIN",   ( 90, 150, 245)),
    "scene_brb":    (0xF786, "BRB",    (245, 185,  75)),
    "cam_toggle":   (0xF03D, "CAM",    ( 90, 225, 155)),
    "clip":         (0xF008, "CLIP",   (190, 135, 250)),
    "screenshot":   (0xF030, "SHOT",   (105, 195, 240)),
    "opencode_old": (0xF120, "CODE",   ( 60, 230, 230)),
    "claude_old":   (0xF4AD, "CLD",    (250, 175, 105)),
    "aider":        (0xF121, "AID",    (165, 235, 125)),
    "whisper":      (0xF130, "WHIS",   (235, 130, 195)),
    "tests":        (0xF0C3, "TEST",   (250, 220,  85)),
    "git":          (0xF126, "GIT",    (255, 140,  85)),
    "clipboard":    (0xF0EA, "PASTE",  (185, 185, 250)),
    "terminal":     (0xF120, "TERM",   ( 90, 235, 180)),
    "work":         (0xF0B1, "WORK",   (250, 160,  70)),
    
    "creatorstack": (0xF135, "VT",     (250, 120,  90)),
    "codex":        (0xF5DC, "CDX",    (130, 250, 160)),
    "lazydocker":   (0xF1B3, "DOCK",   ( 90, 200, 250)),
    "aws":          (0xF0C2, "AWS",    (250, 190,  60)),
    "pomodoro":     (0xF017, "POMO",   (250, 170,  60)),
    # media layer + dashboard
    "media_prev":   (0xF048, "PREV",   (150, 175, 250)),
    "media_play":   (0xF04B, "PLAY",   (120, 230, 170)),
    "media_pause":  (0xF04C, "PAUSE",  (250, 200,  90)),
    "media_next":   (0xF051, "NEXT",   (150, 175, 250)),
    "media_vol":    (0xF028, "VOL",    (120, 200, 250)),
    "dashboard":    (0xF625, "STATS",  (120, 200, 250)),
    "layers":       (0xF5FD, "LAYER",  (200, 150, 250)),
    # system profile
    "sys_cpu":      (0xF2DB, "CPU",    (120, 230, 170)),
    "sys_ram":      (0xF538, "RAM",    (140, 190, 250)),
    "sys_net":      (0xF6FF, "NET",    (120, 200, 250)),
    "sys_disk":     (0xF0A0, "DISK",   (250, 190,  90)),
    "sys_temp":     (0xF769, "TEMP",   (250, 130, 110)),
    "sys_monitor":  (0xF201, "MONITOR",(160, 200, 250)),
    "sys_top":      (0xF233, "HTOP",   (140, 240, 190)),
}

# state-aware tiles: name -> (glyph, caption, accent, glyph fill)
STATE_TILES = {
    "mic_muted":     (0xF131, "MUTED", (255, 90, 90),  (255, 105, 105, 255)),
    "obs_live_on":   (0xF519, "LIVE",  (130, 250, 150), (150, 255, 170, 255)),
    "obs_live_off":  (0xF519, "LIVE",  (95, 98, 110),  (120, 124, 135, 255)),
    "obs_record_on": (0xF111, "REC",   (255, 90, 90),  (255, 110, 110, 255)),
    "obs_record_off":(0xF111, "REC",   (95, 98, 110),  (120, 124, 135, 255)),
    "obs_pause_on":  (0xF04C, "PAUSE", (250, 200, 80), (255, 220, 110, 255)),
    "obs_pause_off": (0xF04C, "PAUSE", (95, 98, 110),  (120, 124, 135, 255)),
}

# real app icons: name -> source PNG on this system
APP_ICONS = {
    "brave":    "/usr/share/icons/hicolor/256x256/apps/brave-browser.png",
    "chrome":   "/usr/share/icons/hicolor/256x256/apps/google-chrome.png",
    "discord":  "/usr/share/pixmaps/discord.png",
    "ghostty":  "/snap/ghostty/current/share/icons/hicolor/128x128/apps/com.mitchellh.ghostty.png",
    "obs":      "/usr/share/icons/hicolor/512x512/apps/com.obsproject.Studio.png",
    "bitwarden":"/var/lib/flatpak/exports/share/icons/hicolor/64x64/apps/com.bitwarden.desktop.png",
    "claude":   "/usr/share/icons/hicolor/256x256/apps/claude-desktop.png",
    "opencode": "/usr/share/icons/hicolor/128x128/apps/ai.opencode.desktop.png",
    "vscode":   "/usr/share/pixmaps/vscode.png",
    "cursor":   os.path.expanduser("~/.local/share/icons/cursor.png"),
    "zed":      os.path.expanduser("~/.local/zed.app/share/icons/hicolor/512x512/apps/zed.png"),
    "github":   "/usr/share/icons/hicolor/1024x1024/apps/github-desktop.png",
    "dbeaver":  "/usr/share/dbeaver-ce/dbeaver.png",
    "whatsapp": "/snap/whatsapp-linux-app/current/meta/gui/icon.png",
    "firefox":  "/usr/share/icons/hicolor/48x48/apps/firefox-esr.png",
    "thunderbird": "/usr/share/icons/hicolor/256x256/apps/thunderbird.png",
    "awsvpn":   "/usr/share/pixmaps/acvc-64.png",
}


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_mask(size, radius):
    mask = Image.new("L", (size * 4, size * 4), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius * 4, fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def dark_tile():
    img = Image.new("RGB", (TILE, TILE))
    for y in range(TILE):
        img.paste(lerp(DARK_TOP, DARK_BOT, y / (TILE - 1)), (0, y, TILE, y + 1))
    gloss = Image.new("L", (TILE, TILE), 0)
    gd = ImageDraw.Draw(gloss)
    gd.ellipse((-TILE // 3, -TILE // 2, TILE + TILE // 3, TILE // 2), fill=46)
    gloss = gloss.filter(ImageFilter.GaussianBlur(10))
    white = Image.new("RGB", (TILE, TILE), (255, 255, 255))
    img = Image.composite(white, img, gloss.point(lambda v: v // 4))
    img.putalpha(rounded_mask(TILE, 18))
    return img


def draw_centered(draw, text, font, cx, cy, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), text, font=font, fill=fill)


def paint_glyph(img, glyph, caption, accent, glyph_fill=(255, 255, 255, 255), alpha=1.0):
    layer = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    gfont = ImageFont.truetype(FA, 42)
    cfont = ImageFont.truetype(SANS, 15)
    g = glyph_fill[:3] + (int(glyph_fill[3] * alpha),)
    a = tuple(accent) + (int(235 * alpha),)
    draw_centered(d, chr(glyph), gfont, TILE / 2, 45, g)
    draw_centered(d, caption, cfont, TILE / 2, 91, a)
    return Image.alpha_composite(img, layer)


def make_icon(glyph, caption, accent):
    return paint_glyph(dark_tile(), glyph, caption, accent).convert("RGB")


def make_app_tile(src_path):
    img = dark_tile()
    icon = Image.open(src_path).convert("RGBA")
    icon.thumbnail((88, 88), Image.LANCZOS)
    img.paste(icon, ((TILE - icon.width) // 2, (TILE - icon.height) // 2), icon)
    return img.convert("RGB")


def make_pulse_icon(glyph, caption, accent, frames=12, lo=0.35):
    return [paint_glyph(dark_tile(), glyph, caption, accent,
                        alpha=lo + (1 - lo) * (0.5 + 0.5 * math.sin(f / frames * 2 * math.pi))
                        ).convert("RGB") for f in range(frames)]


def make_blink_icon(glyph, caption, accent, frames=8):
    out = []
    for f in range(frames):
        img = dark_tile()
        if f < frames * 3 / 4:
            img = paint_glyph(img, glyph, caption, accent)
        else:
            img = paint_glyph(img, glyph, caption, accent, glyph_fill=(255, 255, 255, 60))
        out.append(img.convert("RGB"))
    return out


def make_hue_icon(glyph, caption, accent, frames=16):
    h0 = colorsys.rgb_to_hsv(accent[0] / 255, accent[1] / 255, accent[2] / 255)[0]
    out = []
    for f in range(frames):
        h = (h0 + f / frames * 0.35) % 1.0
        acc = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, 0.75, 1.0))
        out.append(paint_glyph(dark_tile(), glyph, caption, acc).convert("RGB"))
    return out


def main():
    os.makedirs(ICON_DIR, exist_ok=True)
    for name, (glyph, caption, accent) in ICONS.items():
        make_icon(glyph, caption, accent).save(os.path.join(ICON_DIR, name + ".png"))
    print(f"wrote {len(ICONS)} glyph tiles -> {ICON_DIR}")

    for name, (glyph, caption, accent, fill) in STATE_TILES.items():
        paint_glyph(dark_tile(), glyph, caption, accent, glyph_fill=fill).convert("RGB") \
            .save(os.path.join(ICON_DIR, name + ".png"))
    print(f"wrote {len(STATE_TILES)} state tiles -> {ICON_DIR}")

    animated = {
        "obs_live": make_pulse_icon(*ICONS["obs_live"]),
        "obs_record": make_blink_icon(*ICONS["obs_record"]),
        "switch_ai": make_hue_icon(*ICONS["switch_ai"]),
    }
    for name, frames in animated.items():
        frames[0].save(os.path.join(ICON_DIR, name + ".gif"), save_all=True,
                       append_images=frames[1:], duration=100, loop=0, optimize=True)
    print(f"wrote {len(animated)} animated tiles -> {ICON_DIR}")

    missing = []
    for name, src in APP_ICONS.items():
        if os.path.exists(src):
            make_app_tile(src).save(os.path.join(ICON_DIR, name + ".png"))
        else:
            missing.append((name, src))
    print(f"wrote {len(APP_ICONS) - len(missing)} app tiles -> {ICON_DIR}")
    for name, src in missing:
        print(f"  MISSING {name}: {src}")


if __name__ == "__main__":
    main()
