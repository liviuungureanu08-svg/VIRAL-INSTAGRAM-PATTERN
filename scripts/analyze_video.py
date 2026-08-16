#!/usr/bin/env python3
"""Measure a reference video's visual style and pacing.

Turns an MP4 into a structural spec: shot boundaries and their durations, the
colour palette, where text sits in the frame, and how much motion each shot
carries. Output is deliberately small and reviewable — a contact sheet, a JSON
spec, and a markdown report — so it can be committed and read even when the
source video cannot be.

Usage:
    python scripts/analyze_video.py reference/my-video/source.mp4
    python scripts/analyze_video.py source.mp4 --sample-fps 4 --max-frames 400
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

# Frames are compared at this size — small enough to be fast, large enough that a
# genuine cut still dominates ordinary motion.
DIFF_SIZE = (64, 36)
CONTACT_COLUMNS = 5
CONTACT_THUMB_WIDTH = 384

# Absolute floor on what counts as a cut, so sensor noise on static footage does
# not register as an edit.
MIN_CUT_DELTA = 8.0
# Two sampled frames must pass before another cut is allowed.
MIN_SHOT_FRAMES = 2


def find_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("No ffmpeg found. Install ffmpeg or `pip install imageio-ffmpeg`.")


def probe(video: Path, ffmpeg: str) -> dict:
    """Read duration, resolution and fps.

    Uses ffprobe when present, otherwise parses ffmpeg's stderr banner — the
    imageio-ffmpeg wheel ships ffmpeg but not ffprobe, so the fallback matters.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate,duration",
             "-show_entries", "format=duration", "-of", "json", str(video)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            stream = (data.get("streams") or [{}])[0]
            num, _, den = (stream.get("r_frame_rate") or "0/1").partition("/")
            fps = float(num) / float(den) if den and float(den) else 0.0
            duration = float(
                stream.get("duration") or data.get("format", {}).get("duration") or 0
            )
            return {
                "width": int(stream.get("width") or 0),
                "height": int(stream.get("height") or 0),
                "fps": round(fps, 3),
                "duration": round(duration, 3),
            }

    banner = subprocess.run([ffmpeg, "-i", str(video)], capture_output=True, text=True).stderr
    info = {"width": 0, "height": 0, "fps": 0.0, "duration": 0.0}
    if match := re.search(r"Duration: (\d+):(\d+):([\d.]+)", banner):
        h, m, s = match.groups()
        info["duration"] = round(int(h) * 3600 + int(m) * 60 + float(s), 3)
    if match := re.search(r"(\d{2,5})x(\d{2,5})", banner):
        info["width"], info["height"] = int(match.group(1)), int(match.group(2))
    if match := re.search(r"([\d.]+) fps", banner):
        info["fps"] = float(match.group(1))
    return info


def extract_frames(video: Path, out_dir: Path, ffmpeg: str, sample_fps: float, width: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(video),
         "-vf", f"fps={sample_fps},scale={width}:-2", "-q:v", "3",
         str(out_dir / "f_%05d.jpg")],
        check=True,
    )
    return sorted(out_dir.glob("f_*.jpg"))


def detect_cuts(frames: list[Path], sample_fps: float) -> tuple[list[int], list[float]]:
    """Find shot boundaries via inter-frame difference.

    The threshold is derived from the clip's own statistics rather than fixed,
    because a talking-head and a fast-cut montage have completely different
    baseline motion.

    Baseline is median + MAD, not mean + std. Cuts are precisely the outliers
    being looked for, so on a fast-cut edit they drag the mean and standard
    deviation up far enough to hide the smaller cuts behind the bigger ones.
    The median is unmoved by them, so it measures what "no cut" actually looks
    like in this clip.
    """
    signatures = [
        np.asarray(Image.open(f).convert("L").resize(DIFF_SIZE), dtype=np.float32)
        for f in frames
    ]
    diffs = [
        float(np.mean(np.abs(signatures[i] - signatures[i - 1])))
        for i in range(1, len(signatures))
    ]
    if not diffs:
        return [0], []

    arr = np.asarray(diffs)
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    threshold = max(median + 6.0 * mad, median * 2.5, MIN_CUT_DELTA)

    # One cut can straddle two sampled frames; without a refractory gap that
    # registers as a spurious single-frame shot.
    boundaries = [0]
    for i, delta in enumerate(diffs):
        if delta > threshold and (i + 1) - boundaries[-1] >= MIN_SHOT_FRAMES:
            boundaries.append(i + 1)
    return boundaries, diffs


def dominant_colours(image: Image.Image, count: int = 5) -> list[dict]:
    quantised = image.convert("RGB").resize((160, 90)).quantize(colors=count, method=Image.MEDIANCUT)
    palette = quantised.getpalette()[: count * 3]
    total = sum(n for n, _ in quantised.getcolors()) or 1
    out = []
    for pixels, index in sorted(quantised.getcolors(), reverse=True):
        rgb = palette[index * 3 : index * 3 + 3]
        if len(rgb) == 3:
            out.append({
                "rgb": rgb,
                "hex": "#%02x%02x%02x" % tuple(rgb),
                "share": round(pixels / total, 4),
            })
    return out


def text_bands(frames: list[Path], samples: int = 24) -> dict:
    """Estimate where on-screen text sits.

    Text is high-frequency, high-contrast content, so rows containing it show a
    sharp spike in horizontal gradient. Averaging that profile across the clip
    reveals which thirds of the frame the design actually uses.
    """
    step = max(1, len(frames) // samples)
    profiles = []
    for frame in frames[::step]:
        grey = np.asarray(Image.open(frame).convert("L").resize((320, 180)), dtype=np.float32)
        profiles.append(np.abs(np.diff(grey, axis=1)).mean(axis=1))
    if not profiles:
        return {}

    profile = np.mean(profiles, axis=0)
    peak = float(profile.max()) or 1.0
    normalised = profile / peak
    thirds = np.array_split(normalised, 3)

    return {
        "row_activity_top": round(float(thirds[0].mean()), 4),
        "row_activity_middle": round(float(thirds[1].mean()), 4),
        "row_activity_bottom": round(float(thirds[2].mean()), 4),
        "busiest_third": ["top", "middle", "bottom"][int(np.argmax([t.mean() for t in thirds]))],
        "active_row_fraction": round(float((normalised > 0.35).mean()), 4),
    }


def build_contact_sheet(frames: list[Path], indices: list[int], out_path: Path) -> None:
    picks = [frames[i] for i in indices if i < len(frames)][:40]
    if not picks:
        return

    thumbs = []
    for path in picks:
        img = Image.open(path).convert("RGB")
        ratio = CONTACT_THUMB_WIDTH / img.width
        thumbs.append(img.resize((CONTACT_THUMB_WIDTH, max(1, int(img.height * ratio)))))

    cell_w = CONTACT_THUMB_WIDTH
    cell_h = max(t.height for t in thumbs)
    rows = (len(thumbs) + CONTACT_COLUMNS - 1) // CONTACT_COLUMNS
    sheet = Image.new("RGB", (cell_w * CONTACT_COLUMNS, cell_h * rows), (10, 10, 12))

    for i, thumb in enumerate(thumbs):
        x = (i % CONTACT_COLUMNS) * cell_w
        y = (i // CONTACT_COLUMNS) * cell_h
        sheet.paste(thumb, (x, y))

    sheet.save(out_path, quality=88)


def analyse(video: Path, sample_fps: float, max_frames: int, keep_frames: int) -> dict:
    ffmpeg = find_ffmpeg()
    meta = probe(video, ffmpeg)
    print(f"📼 {video.name}: {meta['width']}x{meta['height']} @ {meta['fps']}fps, {meta['duration']}s")

    out_dir = video.parent
    with tempfile.TemporaryDirectory() as tmp:
        frames = extract_frames(video, Path(tmp), ffmpeg, sample_fps, 640)
        if not frames:
            sys.exit("No frames extracted — is the file a valid video?")
        frames = frames[:max_frames]
        print(f"🔍 Sampled {len(frames)} frames at {sample_fps}fps")

        boundaries, diffs = detect_cuts(frames, sample_fps)
        shot_lengths = [
            round((b - a) / sample_fps, 3)
            for a, b in zip(boundaries, boundaries[1:] + [len(frames)])
        ]
        shot_lengths = [s for s in shot_lengths if s > 0]

        palette = dominant_colours(Image.open(frames[len(frames) // 2]))
        bands = text_bands(frames)

        keep_dir = out_dir / "frames"
        if keep_dir.exists():
            shutil.rmtree(keep_dir)
        keep_dir.mkdir(parents=True, exist_ok=True)
        step = max(1, len(boundaries) // keep_frames) if boundaries else 1
        kept = boundaries[::step][:keep_frames]
        for i in kept:
            timestamp = i / sample_fps
            Image.open(frames[i]).save(keep_dir / f"t{timestamp:07.2f}s.jpg", quality=85)

        build_contact_sheet(frames, kept, out_dir / "contact_sheet.jpg")

    aspect = round(meta["width"] / meta["height"], 4) if meta["height"] else 0
    lengths = np.asarray(shot_lengths) if shot_lengths else np.asarray([meta["duration"]])

    spec = {
        "source": video.name,
        "format": {
            "width": meta["width"],
            "height": meta["height"],
            "aspect_ratio": aspect,
            "orientation": "vertical" if aspect < 0.9 else ("square" if aspect < 1.2 else "horizontal"),
            "fps": meta["fps"],
            "duration_seconds": meta["duration"],
        },
        "pacing": {
            "shot_count": len(shot_lengths),
            "cuts_per_minute": round(len(shot_lengths) / (meta["duration"] / 60), 2) if meta["duration"] else 0,
            "shot_length_mean": round(float(lengths.mean()), 3),
            "shot_length_median": round(float(np.median(lengths)), 3),
            "shot_length_min": round(float(lengths.min()), 3),
            "shot_length_max": round(float(lengths.max()), 3),
            "shot_lengths": shot_lengths[:120],
        },
        "motion": {
            "mean_interframe_delta": round(float(np.mean(diffs)), 3) if diffs else 0.0,
            "peak_interframe_delta": round(float(np.max(diffs)), 3) if diffs else 0.0,
            "character": (
                "static" if diffs and np.mean(diffs) < 4
                else "moderate" if diffs and np.mean(diffs) < 12
                else "high-motion"
            ),
        },
        "palette": palette,
        "text_layout": bands,
        "_sampling": {"sample_fps": sample_fps, "frames_analysed": len(frames)},
    }

    (out_dir / "analysis.json").write_text(
        json.dumps(spec, indent=2) + "\n", encoding="utf-8"
    )
    write_report(spec, out_dir / "REPORT.md")

    print(f"✅ {spec['pacing']['shot_count']} shots, "
          f"median {spec['pacing']['shot_length_median']}s, "
          f"{spec['motion']['character']}")
    print(f"   → {out_dir / 'analysis.json'}")
    print(f"   → {out_dir / 'REPORT.md'}")
    print(f"   → {out_dir / 'contact_sheet.jpg'}")
    return spec


def write_report(spec: dict, path: Path) -> None:
    fmt, pace, motion = spec["format"], spec["pacing"], spec["motion"]
    swatches = "\n".join(
        f"| `{c['hex']}` | {c['rgb']} | {c['share'] * 100:.1f}% |" for c in spec["palette"]
    )
    bands = spec["text_layout"]
    lines = f"""# Reference analysis — `{spec['source']}`

## Format
| | |
|---|---|
| Resolution | {fmt['width']} × {fmt['height']} ({fmt['orientation']}) |
| Aspect ratio | {fmt['aspect_ratio']} |
| Frame rate | {fmt['fps']} fps |
| Duration | {fmt['duration_seconds']} s |

## Pacing
| | |
|---|---|
| Shots detected | {pace['shot_count']} |
| Cuts per minute | {pace['cuts_per_minute']} |
| Shot length (median) | **{pace['shot_length_median']} s** |
| Shot length (mean) | {pace['shot_length_mean']} s |
| Shortest / longest | {pace['shot_length_min']} s / {pace['shot_length_max']} s |
| Motion character | **{motion['character']}** (mean Δ {motion['mean_interframe_delta']}) |

Median shot length is the number to copy. It sets how long each generated slide
should hold before cutting.

## Palette (mid-clip frame)
| Hex | RGB | Share |
|---|---|---|
{swatches}

## Text layout
| | |
|---|---|
| Activity, top third | {bands.get('row_activity_top', 'n/a')} |
| Activity, middle third | {bands.get('row_activity_middle', 'n/a')} |
| Activity, bottom third | {bands.get('row_activity_bottom', 'n/a')} |
| Busiest third | **{bands.get('busiest_third', 'n/a')}** |
| Rows carrying detail | {bands.get('active_row_fraction', 'n/a')} |

Higher activity means more high-contrast detail — usually text or graphics.
The busiest third is where this design anchors its message.

## Artifacts
- `contact_sheet.jpg` — one frame per detected shot, for visual review
- `frames/` — the same frames at full sample resolution, named by timestamp
- `analysis.json` — the machine-readable spec
- `transcript.txt` — captions, if the source had any

*Generated by `scripts/analyze_video.py`.*
"""
    path.write_text(lines, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="Path to the video file")
    parser.add_argument("--sample-fps", type=float, default=4.0,
                        help="Frames sampled per second. 4 resolves shots down to ~0.5s; "
                             "raise for faster edits, lower for long videos.")
    parser.add_argument("--max-frames", type=int, default=2400, help="Cap on frames analysed")
    parser.add_argument("--keep-frames", type=int, default=40, help="How many frames to keep on disk")
    args = parser.parse_args()

    if not args.video.exists():
        print(f"❌ Not found: {args.video}", file=sys.stderr)
        return 1

    analyse(args.video, args.sample_fps, args.max_frames, args.keep_frames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
