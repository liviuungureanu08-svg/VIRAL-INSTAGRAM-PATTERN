#!/usr/bin/env python3
"""Autonomous course pipeline: plan -> script -> narrate -> render -> publish.

Run `python main.py` to produce and publish the next pending lesson.
Set DRY_RUN=1 to build the videos without uploading anything.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import traceback
from pathlib import Path

import config
from src.curriculum import (
    GenerationError,
    generate_curriculum,
    generate_lesson_content,
    validate_plan,
)
from src.speech import text_to_speech
from src.uploader import upload_to_youtube
from src.video import create_video
from src.visuals import render_slide, render_thumbnail


def _slug(value: str, limit: int = 40) -> str:
    """Reduce arbitrary model text to a filesystem-safe token."""
    cleaned = re.sub(r"[^\w]+", "_", str(value)).strip("_")
    return (cleaned[:limit] or "untitled").lower()


def load_plan() -> dict:
    """Load the content plan, generating a fresh one if it is missing or broken."""
    if config.CONTENT_PLAN_FILE.exists():
        try:
            raw = json.loads(config.CONTENT_PLAN_FILE.read_text(encoding="utf-8"))
            return validate_plan(raw)
        except (json.JSONDecodeError, GenerationError) as exc:
            print(f"⚠️ Existing plan unusable ({exc}). Regenerating...")

    plan = generate_curriculum()
    save_plan(plan)
    return plan


def save_plan(plan: dict) -> None:
    config.CONTENT_PLAN_FILE.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build_narration(lesson: dict, content: dict) -> tuple[list[dict], list[str]]:
    """Pair display slides with the narration script for each one."""
    intro = {
        "title": lesson["title"],
        "content": f"{lesson['chapter']} · Part {lesson['part']}",
    }
    outro = {
        "title": "Thanks for watching",
        "content": "Subscribe for the next lesson in the series.",
    }

    slides = [intro, *content["long_form_slides"], outro]
    scripts = [
        f"Welcome to {config.SERIES_NAME}. Today's lesson is {lesson['title']}.",
        *[s["content"] for s in content["long_form_slides"]],
        "Thanks for watching. Subscribe for the next lesson in this series.",
    ]
    return slides, scripts


def produce_lesson(lesson: dict) -> str | None:
    """Produce and publish both cuts for one lesson. Returns the long-form video ID."""
    print(f"\n{'=' * 64}\n▶️  {lesson['title']}\n{'=' * 64}")

    run_id = f"{dt.datetime.now():%Y%m%d}_{_slug(lesson['chapter'], 24)}_{_slug(lesson['title'], 32)}"
    content = generate_lesson_content(lesson["title"])

    # --- Long form ---------------------------------------------------------
    print("\n--- Long-form cut ---")
    slides, scripts = build_narration(lesson, content)

    audio_paths = [
        text_to_speech(script, config.OUTPUT_DIR / f"audio_{run_id}_{i:02d}.mp3")
        for i, script in enumerate(scripts, 1)
    ]

    slide_dir = config.OUTPUT_DIR / f"slides_long_{run_id}"
    slide_paths = [
        render_slide(slide_dir, "long", slide, i, len(slides))
        for i, slide in enumerate(slides, 1)
    ]

    long_video = create_video(
        slide_paths,
        audio_paths,
        config.OUTPUT_DIR / f"long_video_{run_id}.mp4",
        "long",
    )
    long_thumb = render_thumbnail(config.OUTPUT_DIR, "long", lesson["title"])

    # --- Short form --------------------------------------------------------
    print("\n--- Short cut ---")
    highlight = content["short_form_highlight"]
    short_audio = text_to_speech(
        f"{highlight}\n\nThe full lesson is linked in the description.",
        config.OUTPUT_DIR / f"short_audio_{run_id}.mp3",
    )
    short_slide = render_slide(
        config.OUTPUT_DIR / f"slides_short_{run_id}",
        "short",
        {"title": "Quick Tip", "content": highlight},
        1,
        1,
    )
    short_video = create_video(
        [short_slide],
        [short_audio],
        config.OUTPUT_DIR / f"short_video_{run_id}.mp4",
        "short",
    )
    short_thumb = render_thumbnail(config.OUTPUT_DIR, "short", f"Quick Tip: {lesson['title']}")

    # --- Publish -----------------------------------------------------------
    print("\n--- Publishing ---")
    hashtags = content["hashtags"]
    long_description = (
        f"Part of {config.SERIES_NAME}.\n\n"
        f"Lesson: {lesson['title']}\n"
        f"{lesson['chapter']} · Part {lesson['part']}\n\n"
        f"{hashtags}"
    )
    tags = ["AI", "programming", "tutorial", *lesson["title"].split()[:6]]

    long_id = upload_to_youtube(long_video, lesson["title"], long_description, tags, long_thumb)
    if not long_id:
        return None

    if config.UPLOAD_GAP_SECONDS and not config.DRY_RUN:
        print(f"⏳ Waiting {config.UPLOAD_GAP_SECONDS}s before the short...")
        import time

        time.sleep(config.UPLOAD_GAP_SECONDS)

    short_title = f"{highlight[:88].rstrip()} #Shorts"
    short_description = (
        f"{highlight}\n\n"
        f"Full lesson: https://www.youtube.com/watch?v={long_id}\n\n"
        f"{hashtags}"
    )
    upload_to_youtube(
        short_video, short_title, short_description, ["shorts", "AI", "tech"], short_thumb
    )

    return long_id


def cleanup() -> None:
    """Remove bulky intermediates; finished MP4s are kept for artifact upload."""
    for pattern in ("*.wav", "*_temp.mp3"):
        for stale in config.OUTPUT_DIR.glob(pattern):
            try:
                stale.unlink()
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=config.LESSONS_PER_RUN,
        help="How many pending lessons to produce this run.",
    )
    args = parser.parse_args()

    print(f"🚀 {config.SERIES_NAME} — autonomous production run")
    if config.DRY_RUN:
        print("🧪 DRY_RUN is on: videos will be built but not uploaded.")

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        plan = load_plan()
    except GenerationError as exc:
        print(f"❌ Could not obtain a content plan: {exc}")
        return 1

    pending = [lesson for lesson in plan["lessons"] if lesson["status"] == "pending"]

    if not pending:
        print("🎉 Every lesson in the plan is complete. Extending the series...")
        try:
            plan = generate_curriculum([lesson["title"] for lesson in plan["lessons"]])
            save_plan(plan)
            pending = [lesson for lesson in plan["lessons"] if lesson["status"] == "pending"]
        except GenerationError as exc:
            print(f"❌ Could not extend the curriculum: {exc}")
            return 1

    if not pending:
        print("⚠️ No pending lessons available after regeneration.")
        return 1

    failures: list[str] = []
    for lesson in pending[: max(1, args.limit)]:
        try:
            video_id = produce_lesson(lesson)
            if video_id:
                lesson["status"] = "complete"
                lesson["youtube_id"] = video_id
                print(f"✅ Completed: {lesson['title']}")
            else:
                failures.append(lesson["title"])
        except Exception:  # noqa: BLE001 - one bad lesson must not lose the others
            print(f"❌ Failed: {lesson['title']}")
            traceback.print_exc()
            failures.append(lesson["title"])
        finally:
            save_plan(plan)

    cleanup()

    if failures:
        print(f"\n❌ {len(failures)} lesson(s) did not complete:")
        for title in failures:
            print(f"   - {title}")
        return 1

    print("\n🏁 Run complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
