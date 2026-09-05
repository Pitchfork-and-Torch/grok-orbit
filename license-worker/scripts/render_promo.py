"""Render Orbit landing hero + OG cards with Fontshare faces. Exact type, no Imagine text."""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public"
KIT = Path.home() / "design-assets" / "fontshare"
CLASH = KIT / "clash-display" / "otf" / "ClashDisplay-Semibold.otf"
SATOSHI = KIT / "satoshi" / "otf" / "Satoshi-Regular.otf"
SATOSHI_MED = KIT / "satoshi" / "otf" / "Satoshi-Medium.otf"

VOID = (10, 12, 16)
VOID2 = (16, 19, 24)
ION = (125, 255, 166)
TEXT = (232, 238, 230)
MUTED = (141, 150, 137)


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def field(w: int, h: int, seed: int = 19) -> Image.Image:
    img = Image.new("RGB", (w, h), VOID)
    px = img.load()
    rng = random.Random(seed)
    # vertical void wash
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(VOID[0] + (VOID2[0] - VOID[0]) * t)
        g = int(VOID[1] + (VOID2[1] - VOID[1]) * t)
        b = int(VOID[2] + (VOID2[2] - VOID[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    glow = Image.new("RGB", (w, h), VOID)
    gd = ImageDraw.Draw(glow)
    cx, cy = int(w * 0.72), int(h * 0.38)
    for i, a in enumerate((28, 16, 8)):
        rad = int(min(w, h) * (0.42 - i * 0.08))
        gd.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=(10 + a, 28 + a, 18 + a))
    glow = glow.filter(ImageFilter.GaussianBlur(46))
    img = Image.blend(img, glow, 0.55)
    d = ImageDraw.Draw(img)
    for _ in range(int(w * h / 2800)):
        x = rng.randint(0, w - 1)
        y = rng.randint(0, h - 1)
        s = rng.choice((1, 1, 1, 2))
        c = rng.randint(70, 170)
        d.ellipse((x, y, x + s, y + s), fill=(c, c + 8, c))
    # a few ion sparks
    for _ in range(14):
        x = rng.randint(0, w - 1)
        y = rng.randint(0, h - 1)
        d.ellipse((x, y, x + 2, y + 2), fill=ION)
    # faint orbit ring
    rx, ry = int(w * 0.70), int(h * 0.40)
    for t in range(0, 360, 2):
        ang = math.radians(t)
        x = int(rx + math.cos(ang) * w * 0.22)
        y = int(ry + math.sin(ang) * h * 0.28)
        if 0 <= x < w and 0 <= y < h:
            img.putpixel((x, y), (40, 70, 52))
    return img


def draw_copy(img: Image.Image, title_size: int, sub_size: int, pad: int) -> None:
    d = ImageDraw.Draw(img)
    clash = font(CLASH, title_size)
    sat = font(SATOSHI, sub_size)
    kicker = font(SATOSHI_MED, max(14, sub_size - 6))
    d.text((pad, pad), "LOCAL COMMAND CENTER", font=kicker, fill=ION)
    d.text((pad, pad + int(sub_size * 1.8)), "Grok Orbit", font=clash, fill=TEXT)
    sub = "One panel for Grok CLI, Grok Bot, grok.com, and other model keys."
    d.text((pad, pad + int(title_size * 1.55) + int(sub_size * 1.6)), sub, font=sat, fill=MUTED)
    foot = "$19 once  ·  Windows  ·  installer is unsigned"
    d.text((pad, img.height - pad - sub_size), foot, font=sat, fill=MUTED)


def save_jpeg(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, "JPEG", quality=90, optimize=True, progressive=True)


def main() -> None:
    if not CLASH.is_file() or not SATOSHI.is_file():
        raise SystemExit(f"missing Fontshare faces under {KIT}")
    hero = field(1600, 720, seed=19)
    draw_copy(hero, 84, 26, 56)
    save_jpeg(hero, OUT / "hero.jpg")
    og = field(1200, 630, seed=21)
    draw_copy(og, 72, 22, 48)
    save_jpeg(og, OUT / "og.jpg")
    print(f"wrote {OUT / 'hero.jpg'}")
    print(f"wrote {OUT / 'og.jpg'}")


if __name__ == "__main__":
    main()
