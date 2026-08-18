"""Scene composition — documentary graphics, not placeholder gradients.

Derived from what the reference channel actually does. Its footage is a mix of
three things, not one: cinematic b-roll, archival material, and **data
graphics** — an annotated elevation map with a scale comparison, a large figure
burned over the frame. The third kind is the one that can be built rather than
generated, and for a story about an impoundment, a water level, a valley and a
sequence of towns it is the more appropriate register anyway.

Each scene renders larger than output (2400x1350) so the renderer can pan and
zoom within it. Nothing is ever static.
"""

from __future__ import annotations

import colorsys
import math
import random
import re
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SW, SH = 2400, 1350          # scene canvas, larger than the 1920x1080 output
INK = (238, 242, 248)
DIM = (140, 152, 172)
FAINT = (74, 84, 100)
ACCENT = (198, 242, 78)
ALERT = (242, 96, 78)
WATER = (86, 132, 190)

FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

# The sixteen miles of hollow, in order from the dams down. Ordering matters:
# the map animates the wave's progress along it.
HOLLOW = ["Saunders", "Pardee", "Lorado", "Craneco", "Lundale", "Stowe", "Crites",
          "Latrobe", "Robinette", "Amherstdale", "Becco", "Fanco", "Riley",
          "Braeholm", "Accoville", "Crown", "Kistler"]


def font(size: int, bold: bool = True):
    for path in (FONTS if bold else FONTS[::-1]):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


@dataclass
class Scene:
    kind: str
    hue: float = 0.58
    figure: str | None = None      # large number to feature
    label: str | None = None
    progress: float = 0.0          # 0..1 — wave position, water level, clock
    seed: int = 0


# --------------------------------------------------------------------------
# Backdrop
# --------------------------------------------------------------------------

def _ground(hue: float, seed: int, dark: float = 1.0) -> Image.Image:
    small = Image.new("RGB", (80, 45))
    px = small.load()
    rnd = random.Random(seed)
    warp = rnd.uniform(0, 6.28)
    for y in range(45):
        for x in range(80):
            t = (x / 80) * 0.55 + (y / 45) * 0.45
            ripple = 0.035 * math.sin(x * 0.3 + y * 0.19 + warp)
            v = max(0.03, min(0.40, (0.10 + t * 0.22 + ripple) * dark))
            r, g, b = colorsys.hsv_to_rgb(hue, max(0.08, 0.40 - t * 0.16), v)
            px[x, y] = (int(r * 255), int(g * 255), int(b * 255))
    return small.resize((SW, SH), Image.BICUBIC).filter(ImageFilter.GaussianBlur(26))


def _rain(img: Image.Image, seed: int, density: int = 340) -> None:
    """Diagonal streaks. Three days of rain is the premise of this episode."""
    d = ImageDraw.Draw(img, "RGBA")
    rnd = random.Random(seed + 991)
    for _ in range(density):
        x, y = rnd.randint(-100, SW), rnd.randint(0, SH)
        ln = rnd.randint(34, 96)
        d.line([(x, y), (x - ln // 3, y + ln)], fill=(190, 205, 225, rnd.randint(14, 42)), width=2)


# --------------------------------------------------------------------------
# Scene kinds
# --------------------------------------------------------------------------

def _scene_hollow(sc: Scene) -> Image.Image:
    """The valley as a line of communities, with the wave travelling down it."""
    img = _ground(sc.hue, sc.seed, 0.8)
    d = ImageDraw.Draw(img, "RGBA")

    x0, x1, y = 210, SW - 210, int(SH * 0.46)
    f_lab, f_small = font(30), font(26, False)

    # Valley walls, drawn as two converging hatched edges
    for side in (-1, 1):
        for i in range(34):
            t = i / 34
            yy = y + side * int(150 + t * 40)
            d.line([(x0 + t * (x1 - x0), yy), (x0 + t * (x1 - x0) + 26, yy + side * 26)],
                   fill=FAINT + (110,), width=2)

    d.line([(x0, y), (x1, y)], fill=FAINT, width=4)
    reach = x0 + (x1 - x0) * max(0.0, min(1.0, sc.progress))
    if sc.progress > 0:
        d.line([(x0, y), (reach, y)], fill=ALERT, width=10)

    step = (x1 - x0) / (len(HOLLOW) - 1)
    for i, name in enumerate(HOLLOW):
        cx = x0 + i * step
        hit = cx <= reach and sc.progress > 0
        r = 13 if hit else 9
        d.ellipse([cx - r, y - r, cx + r, y + r],
                  fill=ALERT if hit else INK, outline=None)
        up = i % 2 == 0
        ty = y - 62 if up else y + 34
        w = d.textlength(name, font=f_small)
        d.text((cx - w / 2, ty), name, font=f_small, fill=INK if hit else DIM)

    d.text((x0, y + 190), "DAMS", font=f_lab, fill=ACCENT)
    t = "SIXTEEN MILES OF HOLLOW"
    d.text((x1 - d.textlength(t, font=f_lab), y + 190), t, font=f_lab, fill=DIM)
    return img


def _scene_impoundment(sc: Scene) -> Image.Image:
    """Cross-section of Dam 3 with the water level as a parameter."""
    img = _ground(sc.hue, sc.seed, 0.85)
    d = ImageDraw.Draw(img, "RGBA")

    base_y, crest_y = int(SH * 0.78), int(SH * 0.30)
    left, right = 620, 1780
    f_lab = font(32)

    # Refuse pile: deliberately irregular, because it was tipped, not built
    rnd = random.Random(sc.seed + 5)
    pile = [(left, base_y)]
    for i in range(15):
        t = i / 14
        pile.append((left + t * (right - left) * 0.42,
                     base_y - t * (base_y - crest_y) + rnd.randint(-9, 9)))
    pile.append((right - (right - left) * 0.30, crest_y + rnd.randint(-6, 6)))
    pile.append((right, base_y))
    d.polygon(pile, fill=(46, 40, 34, 235))

    level = crest_y + (base_y - crest_y) * (1 - max(0.0, min(1.0, sc.progress)))
    d.polygon([(120, level), (left + 40, level), (left + 40, base_y), (120, base_y)],
              fill=WATER + (170,))
    for i in range(9):   # surface chop
        yy = level + i * 3
        d.line([(120, yy), (left + 40, yy)], fill=(150, 190, 235, 40 - i * 4), width=2)

    for x in range(120, left + 40, 30):   # crest reference line
        d.line([(x, crest_y), (x + 16, crest_y)], fill=ACCENT, width=3)
    d.text((130, crest_y - 48), "CREST", font=f_lab, fill=ACCENT)

    if sc.label:
        d.text((130, level - 52), sc.label, font=f_lab, fill=INK)
    d.text((right - 240, base_y + 26), "IMPOUNDMENT 3", font=f_lab, fill=DIM)
    return img


def _scene_figure(sc: Scene) -> Image.Image:
    img = _ground(sc.hue, sc.seed, 0.7)
    d = ImageDraw.Draw(img, "RGBA")
    if sc.figure:
        f = font(340)
        w = d.textlength(sc.figure, font=f)
        # Shrink to fit rather than overflow the canvas
        while w > SW * 0.82 and f.size > 90:
            f = font(int(f.size * 0.88))
            w = d.textlength(sc.figure, font=f)
        x, y = (SW - w) / 2, SH * 0.32
        d.text((x, y), sc.figure, font=f, fill=ACCENT, stroke_width=5, stroke_fill=(0, 0, 0))
        if sc.label:
            fl = font(46)
            lw = d.textlength(sc.label, font=fl)
            d.text(((SW - lw) / 2, y + f.size * 1.05), sc.label.upper(), font=fl, fill=DIM)
    return img


def _scene_clock(sc: Scene) -> Image.Image:
    """A bar across the night into the morning, with a marker."""
    img = _ground(sc.hue, sc.seed, 0.8)
    d = ImageDraw.Draw(img, "RGBA")
    x0, x1, y = 260, SW - 260, int(SH * 0.5)
    f_lab, f_tick = font(34), font(26, False)

    d.line([(x0, y), (x1, y)], fill=FAINT, width=5)
    marks = ["6PM", "9PM", "MIDNIGHT", "3AM", "6AM", "8AM"]
    for i, m in enumerate(marks):
        cx = x0 + (x1 - x0) * i / (len(marks) - 1)
        d.line([(cx, y - 16), (cx, y + 16)], fill=DIM, width=3)
        w = d.textlength(m, font=f_tick)
        d.text((cx - w / 2, y + 34), m, font=f_tick, fill=DIM)

    px = x0 + (x1 - x0) * max(0.0, min(1.0, sc.progress))
    d.line([(x0, y), (px, y)], fill=ACCENT, width=8)
    d.ellipse([px - 17, y - 17, px + 17, y + 17], fill=ACCENT)
    if sc.label:
        w = d.textlength(sc.label, font=f_lab)
        d.text((min(max(px - w / 2, x0), x1 - w), y - 92), sc.label, font=f_lab, fill=INK)
    return img


def _scene_atmosphere(sc: Scene) -> Image.Image:
    img = _ground(sc.hue, sc.seed, 1.0)
    _rain(img, sc.seed)
    return img


RENDERERS = {
    "hollow": _scene_hollow,
    "impoundment": _scene_impoundment,
    "figure": _scene_figure,
    "clock": _scene_clock,
    "atmosphere": _scene_atmosphere,
}


def render_scene(sc: Scene) -> Image.Image:
    return RENDERERS.get(sc.kind, _scene_atmosphere)(sc)


# --------------------------------------------------------------------------
# Choosing a scene from the narration
# --------------------------------------------------------------------------

NUM_RE = re.compile(r"\b\d[\d,\.]*\s?(?:million|billion|thousand)?\b", re.I)

_COMMUNITY_RE = re.compile("|".join(HOLLOW), re.I)
_CLOCK_RE = re.compile(r"\b(morning|night|evening|midnight|o'clock|half past|hours?)\b", re.I)
_WATER_RE = re.compile(r"\b(crest|impoundment|dam ?3|water|inches|rising|reservoir|slurry|refuse)\b", re.I)


def choose(beat: int, text: str, index: int, total: int) -> Scene:
    """Pick a scene from beat and content.

    Deliberately keyword-driven and deterministic: the same script always
    produces the same visuals, which makes the output reviewable rather than
    a lottery.
    """
    hue = (0.58 + beat * 0.028) % 1.0
    through = index / max(1, total - 1)

    communities = len(_COMMUNITY_RE.findall(text))
    if communities >= 2 or "hollow" in text.lower() and communities:
        # Wave progress tracks how far down the named list this line reaches
        last = 0.0
        for i, name in enumerate(HOLLOW):
            if re.search(rf"\b{name}\b", text, re.I):
                last = max(last, (i + 1) / len(HOLLOW))
        return Scene("hollow", hue, progress=last or 0.15, seed=index)

    if _WATER_RE.search(text):
        level = 0.55
        if "one foot below" in text.lower() or "crest" in text.lower():
            level = 0.94
        if "gives way" in text.lower() or "give way" in text.lower():
            level = 1.0
        label = None
        if m := re.search(r"one foot below the crest", text, re.I):
            label = "ONE FOOT BELOW"
        return Scene("impoundment", hue, label=label, progress=level, seed=index)

    if beat in (3, 10) and (found := NUM_RE.findall(text)):
        fig = max(found, key=len).strip()
        return Scene("figure", hue, figure=fig, label=None, seed=index)

    if _CLOCK_RE.search(text) and beat == 7:
        return Scene("clock", hue, label=None, progress=through, seed=index)

    return Scene("atmosphere", hue, seed=index)
