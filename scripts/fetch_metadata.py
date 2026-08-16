#!/usr/bin/env python3
"""Fetch a video's metadata via the YouTube Data API v3.

A supplement to the video analysis, not a replacement. The Data API exposes no
download endpoint — Google never built one — so this yields everything *about*
a video and nothing of its pixels. What it does give is the half of the format
that frame analysis cannot see: the title formula, the description layout, the
tag strategy, and the exact duration.

Unlike scripts/fetch_reference.py this needs no access to youtube.com itself,
only to googleapis.com, so it runs in environments where the video host is
unreachable.

Usage:
    export YOUTUBE_API_KEY=...
    python scripts/fetch_metadata.py "https://youtu.be/VIDEO_ID"
    python scripts/fetch_metadata.py VIDEO_ID --slug reference-01
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = ROOT / "reference"
API_BASE = "https://www.googleapis.com/youtube/v3"
TIMEOUT = 20

ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)
# Matches "0:00", "1:23", "12:34:56" at the start of a description line.
CHAPTER_LINE = re.compile(r"^\s*((?:\d{1,2}:)?\d{1,2}:\d{2})\s+(.+)$")
HASHTAG = re.compile(r"#\w+")
URL_IN_TEXT = re.compile(r"https?://\S+")


class MetadataError(RuntimeError):
    """Raised when metadata could not be retrieved."""


def extract_video_id(value: str) -> str:
    """Accept a full URL in any common shape, or a bare 11-character ID."""
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().removeprefix("www.")

    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if parsed.path == "/watch":
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        else:
            # /shorts/ID, /embed/ID, /live/ID, /v/ID
            parts = [p for p in parsed.path.split("/") if p]
            candidate = parts[1] if len(parts) >= 2 else ""
    else:
        candidate = ""

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        raise MetadataError(f"Could not extract a video ID from {value!r}")
    return candidate


def parse_iso_duration(value: str) -> int:
    """Convert an ISO 8601 duration (PT16M4S) to whole seconds."""
    match = ISO_DURATION.match(value or "")
    if not match:
        return 0
    parts = {k: int(v or 0) for k, v in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def _api_key() -> str:
    key = os.getenv("YOUTUBE_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise MetadataError(
            "No API key. Set YOUTUBE_API_KEY (get one from the Google Cloud Console "
            "with the YouTube Data API v3 enabled)."
        )
    return key


def _redact(text: str, secret: str) -> str:
    """Strip a secret from text bound for logs or the console."""
    return text.replace(secret, "***REDACTED***") if secret else text


def _get(endpoint: str, params: dict) -> dict:
    """Call the Data API, translating its error shapes into readable messages.

    The key travels in the X-goog-api-key header rather than the query string.
    As a query parameter it lands in the request URL, and requests' connection
    errors quote that URL back verbatim — which puts the key straight into any
    log capturing the exception. The redaction below is a second line of
    defence for anything that still manages to echo it.
    """
    key = _api_key()
    try:
        response = requests.get(
            f"{API_BASE}/{endpoint}",
            params=params,
            headers={"X-goog-api-key": key},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MetadataError(
            f"Could not reach the YouTube Data API: {_redact(str(exc), key)}"
        ) from None

    if response.status_code == 403:
        detail = response.json().get("error", {}).get("message", "")
        raise MetadataError(
            f"API refused the request (403). Usually a disabled API, a restricted key, "
            f"or exhausted quota. Google said: {detail}"
        )
    if response.status_code == 400:
        detail = response.json().get("error", {}).get("message", "")
        raise MetadataError(f"Bad request (400) — often an invalid key. Google said: {detail}")
    if not response.ok:
        raise MetadataError(f"API returned HTTP {response.status_code}")

    return response.json()


def fetch_video(video_id: str) -> dict:
    payload = _get(
        "videos",
        {"part": "snippet,contentDetails,statistics,status,topicDetails", "id": video_id},
    )
    items = payload.get("items") or []
    if not items:
        raise MetadataError(
            f"No video found with ID {video_id!r}. It may be private, deleted, or region-locked."
        )
    return items[0]


def fetch_captions(video_id: str) -> list[dict]:
    """List caption tracks. Best-effort — listing is often restricted."""
    try:
        payload = _get("captions", {"part": "snippet", "videoId": video_id})
    except MetadataError:
        return []
    return [
        {
            "language": item["snippet"].get("language"),
            "name": item["snippet"].get("name"),
            "auto_generated": item["snippet"].get("trackKind") == "ASR",
        }
        for item in payload.get("items", [])
    ]


def derive_format_patterns(snippet: dict, duration_seconds: int) -> dict:
    """Extract the replicable shape of the metadata.

    This is the part frame analysis cannot reach: how the title is built, how
    the description is laid out, how tags are used.
    """
    title = snippet.get("title") or ""
    description = snippet.get("description") or ""
    tags = snippet.get("tags") or []
    lines = description.splitlines()

    chapters = []
    for line in lines:
        if match := CHAPTER_LINE.match(line):
            chapters.append({"timestamp": match.group(1), "label": match.group(2).strip()})

    words = title.split()
    return {
        "title": {
            "characters": len(title),
            "words": len(words),
            "contains_number": bool(re.search(r"\d", title)),
            "contains_question": "?" in title,
            "all_caps_words": [w for w in words if len(w) > 2 and w.isupper()],
            "leading_hook": " ".join(words[:5]),
        },
        "description": {
            "characters": len(description),
            "lines": len(lines),
            "blank_line_separated_blocks": len([b for b in description.split("\n\n") if b.strip()]),
            "hashtags": HASHTAG.findall(description),
            "link_count": len(URL_IN_TEXT.findall(description)),
            "has_chapters": bool(chapters),
            "chapter_count": len(chapters),
            "chapters": chapters[:30],
        },
        "tags": {
            "count": len(tags),
            "total_characters": sum(len(t) for t in tags),
            "longest": max(tags, key=len) if tags else None,
            "multi_word_share": (
                round(sum(1 for t in tags if " " in t) / len(tags), 3) if tags else 0
            ),
            "values": tags,
        },
        "duration": {
            "seconds": duration_seconds,
            "formatted": f"{duration_seconds // 60}:{duration_seconds % 60:02d}",
            "is_short": duration_seconds <= 60,
        },
    }


def build(video_id: str) -> dict:
    video = fetch_video(video_id)
    snippet = video.get("snippet", {})
    content = video.get("contentDetails", {})
    stats = video.get("statistics", {})

    duration_seconds = parse_iso_duration(content.get("duration", ""))

    return {
        "id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "channel": snippet.get("channelTitle"),
        "channel_id": snippet.get("channelId"),
        "published_at": snippet.get("publishedAt"),
        "default_language": snippet.get("defaultLanguage") or snippet.get("defaultAudioLanguage"),
        "category_id": snippet.get("categoryId"),
        "tags": snippet.get("tags") or [],
        "thumbnails": {k: v.get("url") for k, v in (snippet.get("thumbnails") or {}).items()},
        "duration_seconds": duration_seconds,
        "definition": content.get("definition"),
        "has_captions": content.get("caption") == "true",
        "caption_tracks": fetch_captions(video_id),
        "statistics": {k: int(v) for k, v in stats.items() if str(v).isdigit()},
        "format_patterns": derive_format_patterns(snippet, duration_seconds),
        "_note": (
            "Metadata only. The YouTube Data API has no download endpoint, so this "
            "carries no visual information — pair it with scripts/analyze_video.py."
        ),
    }


def write_report(data: dict, path: Path) -> None:
    patterns = data["format_patterns"]
    title_p, desc_p, tag_p = patterns["title"], patterns["description"], patterns["tags"]
    stats = data["statistics"]

    chapters = (
        "\n".join(f"| `{c['timestamp']}` | {c['label']} |" for c in desc_p["chapters"])
        or "| — | no chapters in description |"
    )
    tags = ", ".join(f"`{t}`" for t in tag_p["values"][:40]) or "*none published*"

    path.write_text(
        f"""# Metadata — {data['title'] or '(untitled)'}

[{data['url']}]({data['url']}) · {data['channel'] or 'unknown channel'} · published {data['published_at'] or '—'}

## Format
| | |
|---|---|
| Duration | **{patterns['duration']['formatted']}** ({patterns['duration']['seconds']}s) |
| Definition | {data['definition'] or '—'} |
| Language | {data['default_language'] or 'not declared'} |
| Captions | {'yes' if data['has_captions'] else 'no'} ({len(data['caption_tracks'])} track(s) listed) |
| Category ID | {data['category_id'] or '—'} |

## Reach
| | |
|---|---|
| Views | {stats.get('viewCount', '—'):,} |
| Likes | {stats.get('likeCount', '—'):,} |
| Comments | {stats.get('commentCount', '—'):,} |

## Title construction
| | |
|---|---|
| Length | {title_p['characters']} chars, {title_p['words']} words |
| Contains a number | {'yes' if title_p['contains_number'] else 'no'} |
| Phrased as a question | {'yes' if title_p['contains_question'] else 'no'} |
| Words in caps | {', '.join(title_p['all_caps_words']) or '—'} |
| First five words | *{title_p['leading_hook']}* |

## Description construction
| | |
|---|---|
| Length | {desc_p['characters']} chars over {desc_p['lines']} lines |
| Paragraph blocks | {desc_p['blank_line_separated_blocks']} |
| Links | {desc_p['link_count']} |
| Hashtags | {' '.join(desc_p['hashtags']) or '—'} |
| Chapters | {desc_p['chapter_count']} |

| Timestamp | Chapter |
|---|---|
{chapters}

## Tags
{tag_p['count']} tags, {tag_p['total_characters']} characters total,
{tag_p['multi_word_share'] * 100:.0f}% multi-word.

{tags}

---
*Generated by `scripts/fetch_metadata.py`. Metadata only — no visual data.
Pair with `scripts/analyze_video.py` for layout and pacing.*
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Video URL or 11-character ID")
    parser.add_argument("--slug", help="Folder name under reference/ (default: the video ID)")
    parser.add_argument("--stdout", action="store_true", help="Print JSON instead of writing files")
    args = parser.parse_args()

    try:
        video_id = extract_video_id(args.video)
        data = build(video_id)
    except MetadataError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    if args.stdout:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    target = REFERENCE_DIR / (args.slug or video_id)
    target.mkdir(parents=True, exist_ok=True)
    (target / "metadata.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_report(data, target / "METADATA.md")

    patterns = data["format_patterns"]
    print(f"✅ {data['title']}")
    print(f"   duration : {patterns['duration']['formatted']}")
    print(f"   channel  : {data['channel']}")
    print(f"   tags     : {patterns['tags']['count']}")
    print(f"   chapters : {patterns['description']['chapter_count']}")
    print(f"   → {(target / 'metadata.json').relative_to(ROOT)}")
    print(f"   → {(target / 'METADATA.md').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
