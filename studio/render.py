#!/usr/bin/env python3
"""Render an assembled script to a finished 16:9 MP4.

Design notes worth knowing before judging the output:

* **TTS is pluggable.** `EspeakBackend` is the offline fallback and sounds like
  1990s speech synthesis. It exists so the pipeline can be validated end to end
  without network access. `KokoroBackend` and `ElevenLabsBackend` are the
  production paths and produce a completely different result.
* **Backdrops are procedural**, not stock or generated footage. The reference
  channel uses cinematic AI video, which needs a video-generation model. A
  procedural gradient per beat gives visual variety and reads as deliberate,
  which a flat black slide does not.
* **One caption per sentence, one TTS call per caption.** The frame is held for
  exactly that clip's duration, so audio and captions cannot drift — no word-level
  timing required.

Usage:
    python studio/render.py examples/buffalo_creek_1972.json --minutes 25
    python studio/render.py <slots.json> --backend espeak --out out/video.mp4
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

from generator import build  # noqa: E402
import scenes  # noqa: E402

W, H = 1920, 1080
FPS = 24
CAPTION_MAX_CHARS = 96          # two lines of roughly 48
FADE = 0.25
BEAT_CARD_SECONDS = 2.2

# Palette anchors. Hue shifts per beat so sections feel distinct without
# resorting to stock imagery.
BASE_HUE = 0.58                 # cold blue
TEXT = (240, 243, 248)
MUTED = (150, 160, 176)
ACCENT = (198, 242, 78)
BOX = (12, 14, 18)

FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
)


def font(size: int) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def find_ffmpeg() -> str:
    if exe := shutil.which("ffmpeg"):
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


# --------------------------------------------------------------------------
# Voice direction
# --------------------------------------------------------------------------

@dataclass
class Direction:
    """Prosody for one caption.

    Flat narration is a script problem before it is a TTS problem. A uniform
    rate and pitch across 163 captions sounds mechanical even through a good
    voice, so direction is attached here, in the script layer, and each backend
    maps it onto whatever controls it has. Swapping espeak for Kokoro changes
    the timbre; it does not lose the performance.
    """
    rate: int = 165        # words per minute
    pitch: int = 40        # 0-99, espeak scale
    gap: int = 4           # inter-word gap, 10ms units
    pause_after: float = 0.32


# Register per beat, read off the reference corpus: the cold open is slow and
# low, the stat burst is clipped, the epigram is the slowest line in the film.
BEAT_REGISTER: dict[int, Direction] = {
    1:  Direction(rate=150, pitch=34, gap=6, pause_after=0.75),
    2:  Direction(rate=170, pitch=48, gap=3, pause_after=0.60),
    3:  Direction(rate=142, pitch=36, gap=14, pause_after=0.80),
    4:  Direction(rate=152, pitch=34, gap=6, pause_after=0.60),
    5:  Direction(rate=166, pitch=40, gap=4, pause_after=0.38),
    6:  Direction(rate=172, pitch=42, gap=3, pause_after=0.30),
    7:  Direction(rate=168, pitch=40, gap=4, pause_after=0.40),
    8:  Direction(rate=156, pitch=36, gap=6, pause_after=0.55),
    9:  Direction(rate=150, pitch=34, gap=8, pause_after=0.85),
    10: Direction(rate=158, pitch=36, gap=6, pause_after=0.50),
    11: Direction(rate=166, pitch=40, gap=4, pause_after=0.40),
    12: Direction(rate=132, pitch=30, gap=16, pause_after=1.60),
    13: Direction(rate=172, pitch=46, gap=3, pause_after=0.30),
}


def direct(beat: int, text: str, index: int, total: int) -> Direction:
    """Adjust the beat register for this specific line."""
    base = BEAT_REGISTER.get(beat, Direction())
    d = Direction(base.rate, base.pitch, base.gap, base.pause_after)

    words = len(text.split())
    # The flat outcome lines are the whole effect of beat 8. Slow them down and
    # leave silence afterwards instead of running straight into the next caption.
    if words <= 7 and text.rstrip().endswith((".", "!")):
        d.rate = int(d.rate * 0.86)
        d.pitch = max(0, d.pitch - 5)
        d.pause_after = max(d.pause_after, 0.95)
    # Questions lift slightly.
    if text.rstrip().endswith("?"):
        d.pitch = min(99, d.pitch + 8)
    # Beat 7 accelerates as the wave moves down the hollow.
    if beat == 7:
        d.rate = int(d.rate + 12 * (index / max(1, total - 1)))
    return d


# --------------------------------------------------------------------------
# TTS backends
# --------------------------------------------------------------------------

class EspeakBackend:
    """Offline fallback. Robotic by nature — for pipeline validation only."""

    name = "espeak"

    def __init__(self, voice: str = "en-us"):
        self.voice = voice
        if not shutil.which("espeak-ng"):
            raise RuntimeError("espeak-ng not installed (apt install espeak-ng)")

    def synth(self, text: str, out: Path, d: Direction | None = None) -> Path:
        d = d or Direction()
        subprocess.run(
            ["espeak-ng", "-v", self.voice, "-s", str(d.rate), "-p", str(d.pitch),
             "-g", str(d.gap), "-w", str(out), text],
            check=True, capture_output=True,
        )
        return out


class KokoroBackend:
    """Production path. Apache-2.0, 82M params, runs on CPU.

    Needs the model weights, which come from Hugging Face — so this cannot run
    in a network-restricted environment. Works on a laptop or a VPS.
    """

    name = "kokoro"

    def __init__(self, voice: str = "af_heart"):
        from kokoro import KPipeline  # noqa: PLC0415

        self.pipeline = KPipeline(lang_code="a")
        self.voice = voice

    def synth(self, text: str, out: Path, d: Direction | None = None) -> Path:
        import numpy as np  # noqa: PLC0415
        import soundfile as sf  # noqa: PLC0415

        d = d or Direction()
        # Kokoro takes a speed multiplier; map the directed rate onto it.
        speed = max(0.6, min(1.4, d.rate / 165))
        chunks = [audio for _, _, audio in
                  self.pipeline(text, voice=self.voice, speed=speed)]
        sf.write(str(out), np.concatenate(chunks), 24000)
        return out


class ElevenLabsBackend:
    """Production path. Needs ELEVENLABS_API_KEY and burns character quota."""

    name = "elevenlabs"

    def __init__(self, voice_id: str | None = None):
        self.key = os.environ.get("ELEVENLABS_API_KEY")
        if not self.key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

    def synth(self, text: str, out: Path, d: Direction | None = None) -> Path:
        import requests  # noqa: PLC0415

        d = d or Direction()
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}",
            headers={"xi-api-key": self.key, "Content-Type": "application/json"},
            json={"text": text, "model_id": "eleven_multilingual_v2",
                  "voice_settings": {"stability": 0.45, "similarity_boost": 0.75,
                                     "style": 0.35 if d.rate < 150 else 0.15}},
            timeout=90,
        )
        response.raise_for_status()
        out.write_bytes(response.content)
        return out


BACKENDS = {"espeak": EspeakBackend, "kokoro": KokoroBackend, "elevenlabs": ElevenLabsBackend}


# --------------------------------------------------------------------------
# Segmentation
# --------------------------------------------------------------------------

@dataclass
class Segment:
    beat: int
    beat_name: str
    text: str
    is_card: bool = False       # beat title card rather than narration
    callout: str | None = None  # large figure drawn over the frame


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
    return [p.strip() for p in parts if p.strip()]


CLAUSE_RE = re.compile(r"(?<=[,;:])\s+|\s+—\s+|\s+–\s+")


def _split_long(sentence: str, limit: int) -> list[str]:
    """Break an over-long sentence at clause boundaries.

    Without this, a sentence longer than three caption lines gets visually
    truncated while the narration keeps reading it — text silently lost from the
    screen. Splitting at commas and dashes preserves every word and happens to
    match the two-line caption rhythm of the reference.
    """
    if len(sentence) <= limit:
        return [sentence]

    chunks: list[str] = []
    current = ""
    for part in CLAUSE_RE.split(sentence):
        part = part.strip()
        if not part:
            continue
        if not current:
            current = part
        elif len(current) + len(part) + 1 <= limit:
            current = f"{current} {part}"
        else:
            chunks.append(current)
            current = part
    if current:
        chunks.append(current)

    # A clause with no internal punctuation can still exceed the limit; fall
    # back to a word-boundary split so nothing is dropped.
    final: list[str] = []
    for chunk in chunks:
        if len(chunk) <= limit:
            final.append(chunk)
            continue
        # Balance across the needed number of captions rather than filling
        # greedily. Greedy packing leaves the remainder in the last caption,
        # which produces a single orphan word on screen — it reads as a bug.
        words = chunk.split()
        parts = max(2, -(-len(chunk) // limit))
        target = len(chunk) / parts
        cur = ""
        for w in words:
            if cur and len(cur) + len(w) + 1 > limit:
                final.append(cur)
                cur = w
            elif cur and len(cur) >= target and len(final) < parts - 1:
                final.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            final.append(cur)
    return final


def _pack(sentences: list[str], limit: int = CAPTION_MAX_CHARS) -> list[str]:
    """Group sentences into caption-sized units, splitting any that overflow."""
    units: list[str] = []
    for s in sentences:
        units.extend(_split_long(s, limit))

    out: list[str] = []
    current = ""
    for s in units:
        if not current:
            current = s
        elif len(current) + len(s) + 1 <= limit:
            current = f"{current} {s}"
        else:
            out.append(current)
            current = s
    if current:
        out.append(current)
    return out


NUMBER_RE = re.compile(r"\b\d[\d,\.]*\s?(?:million|billion|thousand)?\b", re.I)


def segment_script(script) -> list[Segment]:
    segments: list[Segment] = []
    for beat in script.beats:
        text = beat.text.strip()
        if not text:
            continue

        # Archival inserts are quoted material; keep the >> marker out of speech.
        if beat.beat == 2:
            text = text.replace(">>", " ").strip()

        for unit in _pack(_split_sentences(text)):
            callout = None
            # Beats 3 and 10 are the figure beats — pull the largest number
            # forward as an on-screen callout, the device the reference uses.
            if beat.beat in (3, 10):
                if found := NUMBER_RE.findall(unit):
                    callout = max(found, key=len).strip()
            segments.append(Segment(beat.beat, beat.name, unit, callout=callout))
    return segments


# --------------------------------------------------------------------------
# Frame rendering
# --------------------------------------------------------------------------

def _backdrop(beat: int, seed: int) -> Image.Image:
    """Procedural gradient. Hue derived from the beat so sections read distinctly."""
    hue = (BASE_HUE + beat * 0.035) % 1.0
    small = Image.new("RGB", (64, 36))
    px = small.load()
    for y in range(36):
        for x in range(64):
            # Diagonal falloff plus a slow ripple keeps it from looking like a
            # flat CSS gradient.
            t = (x / 64) * 0.6 + (y / 36) * 0.4
            ripple = 0.04 * math.sin((x * 0.35) + (y * 0.22) + seed * 0.5)
            v = max(0.05, min(0.42, 0.12 + t * 0.24 + ripple))
            s = 0.42 - t * 0.18
            r, g, b = colorsys.hsv_to_rgb(hue, max(0.1, s), v)
            px[x, y] = (int(r * 255), int(g * 255), int(b * 255))
    return small.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(18))


def _wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=fnt) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


SCENE_W, SCENE_H = scenes.SW, scenes.SH
_VIGNETTE = None


def _vignette() -> Image.Image:
    """Soft top and bottom darkening as a vertical gradient.

    Drawn as filled rectangles this leaves hard horizontal seams across the
    frame, which reads as a rendering fault rather than a design choice.
    """
    strip = Image.new("L", (1, SCENE_H), 0)
    px = strip.load()
    top_end, bottom_start = int(SCENE_H * 0.20), int(SCENE_H * 0.50)
    for y in range(SCENE_H):
        if y < top_end:
            alpha = 100 * (1 - y / top_end) ** 1.6
        elif y > bottom_start:
            t = (y - bottom_start) / (SCENE_H - bottom_start)
            alpha = 190 * t ** 1.25
        else:
            alpha = 0
        px[0, y] = int(max(0, min(255, alpha)))
    shade = Image.new("RGB", (SCENE_W, SCENE_H), (0, 0, 0))
    return Image.merge("RGBA", (*shade.split(), strip.resize((SCENE_W, SCENE_H))))


def render_frame(seg: Segment, index: int, total: int, out: Path) -> Path:
    """Compose one caption over its scene, at scene resolution.

    Rendered larger than output so the assembler can pan and zoom inside it.
    """
    global _VIGNETTE
    scene = scenes.choose(seg.beat, seg.text, index, total)
    img = scenes.render_scene(scene).convert("RGBA")

    if _VIGNETTE is None:
        _VIGNETTE = _vignette()
    img = Image.alpha_composite(img, _VIGNETTE).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    k = SCENE_W / W                       # scale factor from output to scene
    f_label = font(int(30 * k))
    f_cap = font(int(52 * k))

    draw.text((int(72 * k), int(54 * k)),
              f"BEAT {seg.beat} · {seg.beat_name.upper()}", font=f_label, fill=MUTED)

    lines = _wrap(draw, seg.text, f_cap, int(SCENE_W * 0.74))[:3]
    line_h = int(74 * k)
    y = int(SCENE_H * 0.79) - (len(lines) * line_h) // 2

    for line in lines:
        tw = draw.textlength(line, font=f_cap)
        x = (SCENE_W - tw) / 2
        draw.rounded_rectangle(
            [x - 26 * k, y - 12 * k, x + tw + 26 * k, y + line_h - 20 * k],
            radius=int(14 * k), fill=BOX + (216,),
        )
        draw.text((x, y - 6 * k), line, font=f_cap, fill=TEXT)
        y += line_h

    draw.rectangle([0, SCENE_H - int(6 * k),
                    int(SCENE_W * (index + 1) / max(1, total)), SCENE_H], fill=ACCENT)

    img.save(out, quality=90)
    return out


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

SEGMENT_PAD = 0.32       # trailing silence after each caption
AUDIO_RATE = 44100


def _audio_duration(path: Path, ffmpeg: str) -> float:
    out = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def _normalise_audio(src: Path, dst: Path, ffmpeg: str, pad: float = SEGMENT_PAD) -> Path:
    """Resample to a common format and append trailing silence.

    Backends differ (espeak gives 22 kHz mono, ElevenLabs 44.1 kHz MP3), and the
    concat demuxer needs every input identical. The padding is what separates one
    caption from the next; folding it into the audio here keeps the frame
    durations and the audio track exactly in step.
    """
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(src),
         "-af", f"aresample={AUDIO_RATE},apad=pad_dur={pad}",
         "-ac", "2", "-ar", str(AUDIO_RATE), "-c:a", "pcm_s16le", str(dst)],
        check=True, capture_output=True,
    )
    return dst


def _segment_clip(frame: Path, audio: Path, out: Path, duration: float,
                  index: int, ffmpeg: str) -> Path:
    """One caption as a short clip with a slow push or pull.

    A held still is a slideshow no matter how good the graphic is. zoompan
    animates inside the oversized scene canvas, so every shot drifts. Direction
    alternates to avoid a metronome feel.
    """
    frames = max(2, int(round(duration * FPS)))
    inward = index % 2 == 0
    zoom = (f"min(1.02+{0.10/frames:.6f}*on,1.12)" if inward
            else f"max(1.12-{0.10/frames:.6f}*on,1.02)")
    drift = 70 if (index // 2) % 2 == 0 else -70
    x = f"iw/2-(iw/zoom/2)+({drift})*on/{frames}"
    y = "ih/2-(ih/zoom/2)"

    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-loop", "1", "-i", str(frame), "-i", str(audio),
         "-filter_complex",
         f"[0:v]zoompan=z='{zoom}':d={frames}:x='{x}':y='{y}':s={W}x{H}:fps={FPS},"
         f"format=yuv420p[v]",
         "-map", "[v]", "-map", "1:a",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)],
        check=True, capture_output=True,
    )
    return out


def assemble_ffmpeg(clips: list[Path], out_path: Path, ffmpeg: str,
                    workdir: Path) -> Path:
    """Join the per-segment clips without re-encoding."""
    listing = workdir / "clips.txt"
    listing.write_text("".join(f"file '{c.name}'\n" for c in clips))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", "clips.txt", "-c", "copy", str(out_path.resolve())],
        check=True, cwd=workdir, capture_output=True,
    )
    return out_path


def render(slots: dict, voice: dict[int, str], out_path: Path,
           backend_name: str = "espeak", minutes: float = 25.0,
           workdir: Path | None = None, limit: int | None = None,
           assembler: str = "ffmpeg") -> Path:
    script = build(slots, target_minutes=minutes, voice=voice)
    if script.validation and not script.validation.ok:
        raise SystemExit("Render blocked by fact validation:\n" + script.validation.report())

    segments = segment_script(script)
    if limit:
        segments = segments[:limit]
    if not segments:
        raise SystemExit("Nothing to render — script is empty.")

    workdir = workdir or out_path.parent / "_work"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    ffmpeg = find_ffmpeg()
    backend = BACKENDS[backend_name]()
    print(f"  backend: {backend.name} | assembler: {assembler} | segments: {len(segments)}")

    clips: list[Path] = []
    for i, seg in enumerate(segments):
        d = direct(seg.beat, seg.text, i, len(segments))
        raw = backend.synth(seg.text, workdir / f"raw{i:04d}.wav", d)
        audio = _normalise_audio(raw, workdir / f"a{i:04d}.wav", ffmpeg, d.pause_after)
        raw.unlink(missing_ok=True)
        frame = render_frame(seg, i, len(segments), workdir / f"f{i:04d}.jpg")
        dur = _audio_duration(audio, ffmpeg)
        clips.append(_segment_clip(frame, audio, workdir / f"c{i:04d}.mp4",
                                   dur, i, ffmpeg))
        frame.unlink(missing_ok=True)
        if (i + 1) % 20 == 0 or i == len(segments) - 1:
            print(f"    {i+1}/{len(segments)} segments")

    assemble_ffmpeg(clips, out_path, ffmpeg, workdir)
    print(f"  ✅ {out_path} ({out_path.stat().st_size/1_000_000:.1f} MB)")
    return out_path


def _assemble_moviepy(frames: list[Path], audios: list[Path], out_path: Path) -> Path:
    """Original assembler, kept as a fallback.

    Retained because it supports per-clip crossfades, which the concat demuxer
    cannot do in one pass. The reference format uses hard cuts, so the fast path
    is both quicker and more faithful — but if a future format needs dissolves,
    this is where they live.
    """
    from moviepy import AudioFileClip, ImageClip, concatenate_videoclips, vfx

    clips, opened = [], []
    for png, wav in zip(frames, audios):
        narration = AudioFileClip(str(wav))
        opened.append(narration)
        clip = (
            ImageClip(str(png))
            .with_duration(narration.duration)
            .with_audio(narration)
            .with_effects([vfx.FadeIn(FADE), vfx.FadeOut(FADE)])
        )
        clips.append(clip)
        opened.append(clip)

    video = concatenate_videoclips(clips, method="compose")
    opened.append(video)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    video.write_videofile(
        str(out_path), fps=FPS, codec="libx264", audio_codec="aac",
        audio_bitrate="160k", preset="veryfast", threads=4, logger=None,
    )
    for c in opened:
        try:
            c.close()
        except Exception:
            pass
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slots", type=Path, help="Slot document JSON (with optional 'voice')")
    ap.add_argument("--out", type=Path, default=HERE / "examples/out/video.mp4")
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="espeak")
    ap.add_argument("--minutes", type=float, default=25.0)
    ap.add_argument("--limit", type=int, help="Render only the first N segments")
    ap.add_argument("--assembler", choices=("ffmpeg","moviepy"), default="ffmpeg",
                    help="ffmpeg concat (fast, hard cuts) or moviepy (slow, supports fades)")
    ap.add_argument("--simulate-gates", action="store_true",
                    help="Fill the human-review gates for a demo render. Never use for publishing.")
    args = ap.parse_args()

    doc = json.loads(args.slots.read_text())
    slots = doc.get("slots", doc)
    voice = {int(k): v for k, v in (doc.get("voice") or {}).items()}

    if args.simulate_gates:
        print("  ⚠ simulating human-review gates — output is NOT publishable")
        for person in slots.get("people", []):
            person["family_sensitivity_reviewed"] = True
        if not slots.get("archival_audio") or not slots["archival_audio"][0].get("source"):
            slots["archival_audio"] = [{
                "description": "SIMULATED", "transcript": "", "rights_basis": "SIMULATED",
                "source": {"body": "SIMULATED", "title": "placeholder",
                           "date": "n.d.", "locator": "n/a", "tier": "B"},
            }]

    render(slots, voice, args.out, args.backend, args.minutes, limit=args.limit,
           assembler=args.assembler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
