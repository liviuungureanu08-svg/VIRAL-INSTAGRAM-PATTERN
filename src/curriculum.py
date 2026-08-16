"""Gemini-backed curriculum and lesson generation.

Model output is treated as untrusted input: every response is parsed
defensively and validated against an expected shape before the rest of the
pipeline is allowed to build filenames or video frames from it.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from google import genai

import config


class GenerationError(RuntimeError):
    """Raised when the model returns something the pipeline cannot use."""


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def _client() -> genai.Client:
    api_key = os.environ.get(config.GOOGLE_API_KEY_VAR)
    if not api_key:
        raise GenerationError(
            f"{config.GOOGLE_API_KEY_VAR} is not set. Export it locally or add it "
            "as a repository secret."
        )
    return genai.Client(api_key=api_key)


def _extract_json(raw: str) -> Any:
    """Pull a JSON document out of a model response.

    Models wrap JSON in prose or code fences unpredictably, so strip fences
    first and fall back to the outermost brace-balanced span.
    """
    if not raw or not raw.strip():
        raise GenerationError("Model returned an empty response.")

    cleaned = _FENCE_RE.sub("", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise GenerationError(f"No JSON object found in response: {cleaned[:200]!r}")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GenerationError(f"Malformed JSON in response: {exc}") from exc


def _generate(prompt: str) -> Any:
    response = _client().models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
    )
    return _extract_json(getattr(response, "text", "") or "")


def _clean_text(value: Any, *, limit: int = 1200) -> str:
    """Collapse a model-supplied value to safe, renderable single-spaced text."""
    text = str(value or "").replace("\r", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()[:limit]


def validate_plan(plan: Any) -> dict:
    """Ensure a content plan has the shape the pipeline depends on."""
    if not isinstance(plan, dict):
        raise GenerationError("Content plan must be a JSON object.")

    lessons = plan.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        raise GenerationError("Content plan must contain a non-empty 'lessons' list.")

    normalised = []
    for index, lesson in enumerate(lessons, start=1):
        if not isinstance(lesson, dict):
            continue
        title = _clean_text(lesson.get("title"), limit=200)
        if not title:
            continue
        status = str(lesson.get("status") or "pending").lower()
        normalised.append(
            {
                "chapter": _clean_text(lesson.get("chapter") or "General", limit=120),
                "part": lesson.get("part") if isinstance(lesson.get("part"), int) else index,
                "title": title,
                "status": status if status in {"pending", "complete"} else "pending",
                "youtube_id": lesson.get("youtube_id") or None,
            }
        )

    if not normalised:
        raise GenerationError("Content plan contained no usable lessons.")
    return {"lessons": normalised}


def validate_lesson_content(content: Any) -> dict:
    """Ensure generated lesson content is renderable."""
    if not isinstance(content, dict):
        raise GenerationError("Lesson content must be a JSON object.")

    raw_slides = content.get("long_form_slides")
    if not isinstance(raw_slides, list) or not raw_slides:
        raise GenerationError("Lesson content must contain 'long_form_slides'.")

    slides = []
    for slide in raw_slides:
        if not isinstance(slide, dict):
            continue
        title = _clean_text(slide.get("title"), limit=160)
        body = _clean_text(slide.get("content"))
        if title and body:
            slides.append({"title": title, "content": body})

    if not slides:
        raise GenerationError("No slides in the response had both a title and content.")

    highlight = _clean_text(content.get("short_form_highlight"), limit=400)
    if not highlight:
        highlight = slides[0]["content"][:200]

    hashtags = _clean_text(content.get("hashtags"), limit=200) or "#AI #Developer #LearnAI"

    return {
        "long_form_slides": slides,
        "short_form_highlight": highlight,
        "hashtags": hashtags,
    }


def generate_curriculum(previous_titles: list[str] | None = None) -> dict:
    """Generate a fresh course plan, optionally continuing a finished series."""
    print("🤖 Generating a new curriculum...")

    history = ""
    if previous_titles:
        formatted = "\n".join(f"{i}. {t}" for i, t in enumerate(previous_titles, 1))
        history = (
            "These lessons already exist — continue the series without repeating "
            f"them:\n{formatted}\n"
        )

    prompt = f"""
You are an expert curriculum designer building a YouTube series called
'{config.SERIES_NAME}'.

{history}
Audience: {config.SERIES_AUDIENCE}
Subject: {config.SERIES_TOPIC}

Teaching style: open each lesson with a concrete real-world analogy, then
connect it to the technical mechanism. Never assume prior theory. Progress from
foundations to advanced material across the series.

Respond with ONLY a valid JSON object containing a key "lessons": a list of
exactly {config.LESSONS_PER_PLAN} lesson objects. Each object must have:
  "chapter"    - string, the section this lesson belongs to
  "part"       - integer, the lesson's position in the series
  "title"      - string, a specific and searchable lesson title
  "status"     - always the string "pending"
  "youtube_id" - always null
"""
    plan = validate_plan(_generate(prompt))
    print(f"✅ Curriculum generated with {len(plan['lessons'])} lessons.")
    return plan


def generate_lesson_content(lesson_title: str) -> dict:
    """Generate slide content plus a short-form highlight for one lesson."""
    print(f"🤖 Generating content for: {lesson_title!r}")

    prompt = f"""
You are writing one lesson for the series '{config.SERIES_NAME}'.
The lesson topic is: '{lesson_title}'.

Audience: {config.SERIES_AUDIENCE}
Use plain language and concrete analogies. Explain every term you introduce.

Respond with ONLY a valid JSON object with exactly these three keys:
1. "long_form_slides": a list of {config.SLIDES_PER_LESSON} objects, each with
   "title" (a short slide heading, under 8 words) and "content" (2-4 sentences
   of spoken narration for that slide, under 90 words).
2. "short_form_highlight": one punchy 1-2 sentence takeaway for a vertical short.
3. "hashtags": a single string of 5-7 space-separated hashtags.
"""
    content = validate_lesson_content(_generate(prompt))
    print(f"✅ Lesson content generated ({len(content['long_form_slides'])} slides).")
    return content
