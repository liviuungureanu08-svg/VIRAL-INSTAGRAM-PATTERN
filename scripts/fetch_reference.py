#!/usr/bin/env python3
"""Download a reference video and its metadata for style analysis.

Run this where YouTube is reachable — your own machine, or the
`analyze-reference` GitHub Actions workflow. The analysis container itself has
no egress to YouTube, which is why fetching and analysing are separate steps:
this script pulls the raw material, `analyze_video.py` turns it into a spec, and
only the small derived artifacts are committed.

Usage:
    python scripts/fetch_reference.py "https://www.youtube.com/watch?v=..."
    python scripts/fetch_reference.py URL --slug my-reference --max-height 720
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = ROOT / "reference"

# Metadata fields worth keeping. The raw info dict from yt-dlp is enormous and
# mostly CDN URLs that expire within hours.
META_FIELDS = (
    "id", "title", "description", "uploader", "channel", "channel_id",
    "duration", "width", "height", "fps", "vcodec", "acodec", "aspect_ratio",
    "upload_date", "view_count", "like_count", "comment_count",
    "tags", "categories", "chapters", "language", "webpage_url",
)


def slugify(value: str, limit: int = 48) -> str:
    cleaned = re.sub(r"[^\w]+", "-", str(value)).strip("-").lower()
    return cleaned[:limit] or "reference"


def _require_yt_dlp():
    try:
        import yt_dlp  # noqa: PLC0415
    except ImportError:
        sys.exit(
            "yt-dlp is not installed.\n"
            "  pip install -r requirements-analysis.txt"
        )
    return yt_dlp


def subtitles_to_transcript(vtt_path: Path) -> str:
    """Flatten a WebVTT caption file into deduplicated plain text.

    YouTube's auto-captions repeat each line across overlapping cues to create
    a rolling effect, so naive extraction produces every phrase two or three
    times. Consecutive duplicates are collapsed.
    """
    lines: list[str] = []
    for raw in vtt_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if (
            not line
            or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE"))
            or "-->" in line
            or line.isdigit()
        ):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()  # inline karaoke timing tags
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n".join(lines)


def fetch(url: str, slug: str | None = None, max_height: int = 1080) -> Path:
    yt_dlp = _require_yt_dlp()

    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    probe_opts = {"quiet": True, "no_warnings": True, "skip_download": True}

    with yt_dlp.YoutubeDL(probe_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    slug = slug or slugify(info.get("title") or info.get("id") or "reference")
    target = REFERENCE_DIR / slug
    target.mkdir(parents=True, exist_ok=True)

    download_opts = {
        "quiet": False,
        "no_warnings": True,
        "outtmpl": str(target / "source.%(ext)s"),
        # Cap resolution: analysis works fine at 720-1080p and the file is never
        # committed, so pulling a 4K master wastes bandwidth and disk.
        "format": f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={max_height}]/best",
        "merge_output_format": "mp4",
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-GB"],
        "subtitlesformat": "vtt",
        "postprocessors": [],
    }

    with yt_dlp.YoutubeDL(download_opts) as ydl:
        ydl.download([url])

    metadata = {key: info.get(key) for key in META_FIELDS}
    (target / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    transcript_written = False
    for vtt in sorted(target.glob("source*.vtt")):
        transcript = subtitles_to_transcript(vtt)
        if transcript.strip():
            (target / "transcript.txt").write_text(transcript + "\n", encoding="utf-8")
            transcript_written = True
            break

    print(f"\n✅ Fetched: {metadata.get('title')}")
    print(f"   duration : {metadata.get('duration')}s")
    print(f"   native   : {metadata.get('width')}x{metadata.get('height')} @ {metadata.get('fps')}fps")
    print(f"   transcript: {'yes' if transcript_written else 'NOT AVAILABLE (no captions)'}")
    print(f"   folder   : {target.relative_to(ROOT)}")
    print(f"\nNext: python scripts/analyze_video.py {target.relative_to(ROOT)}/source.mp4")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="YouTube (or any yt-dlp supported) video URL")
    parser.add_argument("--slug", help="Folder name under reference/ (default: from title)")
    parser.add_argument("--max-height", type=int, default=1080, help="Cap download resolution")
    args = parser.parse_args()

    try:
        fetch(args.url, args.slug, args.max_height)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Fetch failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
