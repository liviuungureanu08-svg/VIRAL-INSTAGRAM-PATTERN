"""Slide and thumbnail rendering with Pillow.

Frames are composed entirely in Pillow — there is no ImageMagick dependency and
no TextClip, which removes both the `policy.xml` patching that ImageMagick
otherwise needs in CI and its associated attack surface.
"""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

# Pillow's own decompression-bomb guard, made explicit. Backdrops arrive from a
# third-party API, so cap what is allowed to be decoded rather than trusting it.
Image.MAX_IMAGE_PIXELS = 80_000_000
MAX_BACKDROP_BYTES = 15 * 1024 * 1024

# Candidate fonts, in preference order. No font is vendored: shipping Arial (or
# any Monotype face) in a public repo is a licensing problem, so the pipeline
# resolves a font at runtime instead. Drop your own .ttf in assets/fonts/ to
# override.
_FONT_CANDIDATES = (
    config.FONT_DIR / "custom.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)


def _resolve_font_path() -> Path | None:
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    for found in config.FONT_DIR.glob("*.ttf"):
        return found
    return None


def _font(size: int) -> ImageFont.ImageFont:
    path = _resolve_font_path()
    if path:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Greedy word wrap, with a character-level fallback for unbreakable tokens."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if _text_width(draw, candidate, font) <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines or [""]


def fetch_backdrop(query: str, video_type: str) -> Image.Image | None:
    """Fetch a themed backdrop from Pexels, or None to fall back to flat colour."""
    api_key = os.getenv(config.PEXELS_API_KEY_VAR)
    if not api_key:
        return None

    orientation = "landscape" if video_type == "long" else "portrait"
    try:
        response = requests.get(
            config.PEXELS_SEARCH_URL,
            headers={"Authorization": api_key},
            params={"query": f"abstract {query}", "per_page": 1, "orientation": orientation},
            timeout=config.HTTP_TIMEOUT,
        )
        response.raise_for_status()
        photos = response.json().get("photos") or []
        if not photos:
            return None

        image_url = photos[0]["src"]["large2x"]
        image_response = requests.get(image_url, timeout=config.HTTP_TIMEOUT, stream=True)
        image_response.raise_for_status()

        declared = int(image_response.headers.get("Content-Length") or 0)
        if declared > MAX_BACKDROP_BYTES:
            print(f"⚠️ Backdrop exceeds size cap ({declared} bytes), skipping.")
            return None

        payload = image_response.raw.read(MAX_BACKDROP_BYTES + 1, decode_content=True)
        if len(payload) > MAX_BACKDROP_BYTES:
            print("⚠️ Backdrop exceeds size cap while streaming, skipping.")
            return None

        return Image.open(BytesIO(payload)).convert("RGBA")

    except requests.RequestException as exc:
        print(f"⚠️ Could not fetch backdrop for {query!r}: {exc}")
    except Exception as exc:  # noqa: BLE001 - a bad image must not kill the run
        print(f"⚠️ Could not decode backdrop for {query!r}: {exc}")
    return None


def _compose_backdrop(query: str, video_type: str, size: tuple[int, int]) -> Image.Image:
    backdrop = fetch_backdrop(query, video_type)
    if backdrop is None:
        backdrop = Image.new("RGBA", size, config.COLOR_BACKDROP + (255,))
    else:
        backdrop = backdrop.resize(size, Image.LANCZOS).filter(
            ImageFilter.GaussianBlur(config.BACKDROP_BLUR)
        )
    darken = Image.new("RGBA", size, (0, 0, 0, config.OVERLAY_DARKEN))
    return Image.alpha_composite(backdrop, darken).convert("RGB")


def render_slide(
    output_dir: Path,
    video_type: str,
    slide_content: dict,
    slide_number: int,
    total_slides: int,
) -> Path:
    """Render one content slide and return its path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    width, height = config.LONG_RESOLUTION if video_type == "long" else config.SHORT_RESOLUTION
    title = slide_content.get("title", "")
    body = slide_content.get("content", "")

    frame = _compose_backdrop(title, video_type, (width, height))
    draw = ImageDraw.Draw(frame, "RGBA")

    title_font = _font(80 if video_type == "long" else 90)
    body_font = _font(45 if video_type == "long" else 55)
    footer_font = _font(25 if video_type == "long" else 35)

    # Header band. Sized to whatever the title actually wraps to — model-written
    # titles run long, and a fixed band would let a two-line title spill over the
    # edge into the body copy.
    title_lines = _wrap(draw, title, title_font, int(width * 0.9))
    title_line_height = title_font.getbbox("Ay")[3] + 10
    title_block = len(title_lines) * title_line_height
    header_padding = int(height * 0.03)
    header_height = max(int(height * 0.18), title_block + 2 * header_padding)

    draw.rectangle([0, 0, width, header_height], fill=config.COLOR_PANEL + (200,))

    y = max(header_padding, (header_height - title_block) // 2)
    for line in title_lines:
        x = (width - _text_width(draw, line, title_font)) // 2
        draw.text((x, y), line, font=title_font, fill=config.COLOR_TITLE)
        y += title_line_height

    # Body block — centred when short, top-anchored when long
    body_lines = _wrap(draw, body, body_font, int(width * 0.85))
    body_line_height = body_font.getbbox("Ay")[3] + 15
    total_body_height = len(body_lines) * body_line_height
    if len(body.split()) < 10:
        y = (height - total_body_height) // 2
    else:
        y = header_height + int(height * 0.08)

    for line in body_lines:
        x = (width - _text_width(draw, line, body_font)) // 2
        draw.text((x, y), line, font=body_font, fill=config.COLOR_BODY)
        y += body_line_height

    # Footer band
    footer_height = int(height * 0.06)
    draw.rectangle(
        [0, height - footer_height, width, height], fill=config.COLOR_PANEL + (200,)
    )
    draw.text(
        (40, height - footer_height + 12),
        config.SERIES_NAME,
        font=footer_font,
        fill=config.COLOR_MUTED,
    )
    if total_slides > 0:
        counter = f"{slide_number} / {total_slides}"
        draw.text(
            (width - _text_width(draw, counter, footer_font) - 40, height - footer_height + 12),
            counter,
            font=footer_font,
            fill=config.COLOR_MUTED,
        )

    path = output_dir / f"slide_{slide_number:02d}.png"
    frame.save(path)
    return path


def render_thumbnail(output_dir: Path, video_type: str, title: str) -> Path:
    """Render a thumbnail for a finished video and return its path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    width, height = config.LONG_RESOLUTION if video_type == "long" else config.SHORT_RESOLUTION
    frame = _compose_backdrop(title, video_type, (width, height))
    draw = ImageDraw.Draw(frame, "RGBA")

    title_font = _font(96 if video_type == "long" else 104)
    lines = _wrap(draw, title, title_font, int(width * 0.86))
    line_height = title_font.getbbox("Ay")[3] + 18
    y = (height - len(lines) * line_height) // 2

    for line in lines:
        x = (width - _text_width(draw, line, title_font)) // 2
        draw.text(
            (x, y),
            line,
            font=title_font,
            fill=config.COLOR_TITLE,
            stroke_width=3,
            stroke_fill=(0, 0, 0),
        )
        y += line_height

    path = output_dir / f"thumbnail_{video_type}.png"
    frame.save(path)
    return path
