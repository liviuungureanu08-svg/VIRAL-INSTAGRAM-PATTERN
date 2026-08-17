"""Script assembly — turns validated fact slots into a narration script.

The division of labour from docs/FACT-SLOTS.md is enforced structurally here,
not by asking a model to behave:

  * Voice beats (1, 3, 4, 6, 9, 12, 13) are model-authored from prompts that are
    handed the thesis and nothing else factual.
  * Record beats (5, 7, 8, 10, 11) are rendered from slot values by string
    formatting. No model ever sees a blank it could helpfully fill.

A model cannot invent a death toll it was never asked to write.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from schema import ValidationResult, validate

WORDS_PER_MINUTE = 150

VOICE_BEATS = (1, 3, 4, 6, 9, 12, 13)
RECORD_BEATS = (2, 5, 7, 8, 10, 11)

# Beat number -> (name, share of total words). Shares sum to 1.0 and are derived
# from the corpus proportions in docs/SCRIPT-ARCHITECTURE.md.
BEAT_PLAN: dict[int, tuple[str, float]] = {
    1:  ("Cold open", 0.020),
    2:  ("Archival audio insert", 0.016),
    3:  ("Stat burst", 0.007),
    4:  ("Thesis turn", 0.027),
    5:  ("Foreknowledge", 0.080),
    6:  ("Signposted background", 0.127),
    7:  ("Timestamped escalation", 0.280),
    8:  ("Named people", 0.200),
    9:  ("Forward-pull closers", 0.027),
    10: ("Aftermath numbers", 0.080),
    11: ("Institutional reckoning", 0.093),
    12: ("Epigram", 0.008),
    13: ("Outro", 0.035),
}


@dataclass
class BeatOutput:
    beat: int
    name: str
    kind: str            # "voice" | "record"
    target_words: int
    text: str = ""
    sources: list[str] = field(default_factory=list)

    @property
    def actual_words(self) -> int:
        return len(self.text.split())


@dataclass
class Script:
    beats: list[BeatOutput] = field(default_factory=list)
    validation: ValidationResult | None = None

    @property
    def word_count(self) -> int:
        return sum(b.actual_words for b in self.beats)

    @property
    def runtime_minutes(self) -> float:
        return round(self.word_count / WORDS_PER_MINUTE, 1)

    def narration(self) -> str:
        """Clean text for TTS — no beat markers, no citations."""
        return "\n\n".join(b.text.strip() for b in self.beats if b.text.strip())

    def annotated(self) -> str:
        """Reviewable form — beat markers, word counts, per-beat sources."""
        out = [
            f"# Script — {self.word_count} words · ~{self.runtime_minutes} min\n",
        ]
        for b in self.beats:
            drift = b.actual_words - b.target_words
            flag = "" if abs(drift) <= max(15, b.target_words * 0.25) else f"  ⚠ {drift:+d} vs target"
            out.append(f"\n## Beat {b.beat} — {b.name} [{b.kind}]")
            out.append(f"*{b.actual_words} words (target {b.target_words}){flag}*\n")
            out.append(b.text.strip() or "*(empty)*")
            if b.sources:
                out.append("\n**Sources:** " + " · ".join(dict.fromkeys(b.sources)))
        return "\n".join(out)

    def source_appendix(self) -> str:
        seen: dict[str, None] = {}
        for b in self.beats:
            for s in b.sources:
                seen.setdefault(s, None)
        if not seen:
            return "*(no sources)*"
        return "\n".join(f"{i}. {s}" for i, s in enumerate(seen, 1))


def _fmt_source(source: Any) -> str:
    if not isinstance(source, dict):
        return str(source)
    bits = [source.get("body"), source.get("title"), source.get("date"), source.get("locator")]
    tier = source.get("tier", "?")
    return f"[{tier}] " + ", ".join(str(b) for b in bits if b)


def _budget(total_words: int) -> dict[int, int]:
    return {n: max(10, round(total_words * share)) for n, (_, share) in BEAT_PLAN.items()}


# --------------------------------------------------------------------------
# Record beats — rendered from slots by formatting only
# --------------------------------------------------------------------------

def _render_archival(slots: dict) -> tuple[str, list[str]]:
    lines, sources = [], []
    for clip in slots.get("archival_audio", [])[:2]:
        transcript = str(clip.get("transcript", "")).strip()
        if transcript:
            lines.append(f">> {transcript}")
        sources.append(_fmt_source(clip.get("source")))
    return "\n".join(lines), sources


def _render_foreknowledge(slots: dict) -> tuple[str, list[str]]:
    parts, sources = [], []
    for item in slots.get("foreknowledge", []):
        sentence = []
        date = str(item.get("date", "")).strip()
        name = str(item.get("document_name", "")).strip()
        body = str(item.get("commissioning_body", "")).strip()
        lead = f"In {date}, " if date else ""
        if body:
            sentence.append(f"{lead}{body} produced {name}.")
        else:
            sentence.append(f"{lead}{name}.")
        if pred := str(item.get("prediction", "")).strip():
            sentence.append(f"It predicted {pred}.")
        if resp := str(item.get("response", "")).strip():
            sentence.append(f"{resp}.")
        if quote := str(item.get("quote", "")).strip():
            attribution = str(item.get("quote_attribution", "")).strip()
            sentence.append(f'One account put it this way: "{quote}."'
                            + (f" — {attribution}" if attribution else ""))
        parts.append(" ".join(sentence))
        sources.append(_fmt_source(item.get("source")))
    return "\n\n".join(parts), sources


def _render_timeline(slots: dict) -> tuple[str, list[str]]:
    parts, sources = [], []
    for item in slots.get("timeline", []):
        stamp = str(item.get("timestamp_local", "")).strip()
        event = str(item.get("event", "")).strip()
        display = str(item.get("display_time", "")).strip() or stamp
        line = f"At {display}, {event[0].lower() + event[1:] if event else ''}."
        if m := item.get("measurement"):
            if isinstance(m, dict) and m.get("value") is not None:
                line += f" {m['value']} {m.get('unit', '')}".rstrip() + "."
        parts.append(line)
        sources.append(_fmt_source(item.get("source")))
    return "\n\n".join(parts), sources


def _render_people(slots: dict) -> tuple[str, list[str]]:
    parts, sources = [], []
    for person in slots.get("people", []):
        name = str(person.get("full_name", "")).strip()
        age = person.get("age")
        role = str(person.get("role", "")).strip()
        detail = str(person.get("humanising_detail", "")).strip()
        outcome = str(person.get("outcome_line", "")).strip()

        opening = name
        if age:
            opening += f" is {age}"
            opening += f", {role}." if role else "."
        elif role:
            opening += f" is {role}."
        else:
            opening += "."

        block = [opening]
        if detail:
            block.append(detail if detail.endswith(".") else detail + ".")
        if person.get("final_words") and person.get("final_words_verbatim"):
            block.append(f'"{person["final_words"]}"')
        block.append(outcome)

        parts.append(" ".join(block))
        sources.append(_fmt_source(person.get("source")))
        if person.get("final_words_source"):
            sources.append(_fmt_source(person["final_words_source"]))
    return "\n\n".join(parts), sources


def _render_aftermath(slots: dict) -> tuple[str, list[str]]:
    LABELS = {
        "death_toll": "The official death toll stands at {v}",
        "damage_usd": "Total damage reaches ${v}",
        "structures_destroyed": "{v} structures are destroyed",
        "area_affected": "{v} affected",
        "population_change": "Population falls from {before} to {after}",
    }
    parts, sources = [], []
    for key, value in (slots.get("aftermath") or {}).items():
        if not isinstance(value, dict):
            continue
        template = LABELS.get(key, key.replace("_", " ").capitalize() + ": {v}")
        if key == "population_change":
            before, after = value.get("before"), value.get("after")
            if before is None or after is None:
                continue
            text = template.format(before=f"{before:,}", after=f"{after:,}")
        else:
            v = value.get("value")
            if v in (None, ""):
                continue
            shown = f"{v:,}" if isinstance(v, (int, float)) else str(v)
            if unit := value.get("unit"):
                shown += f" {unit}"
            text = template.format(v=shown)
        if body := value.get("revising_body"):
            text += f", revised by {body}"
        parts.append(text + ".")
        sources.append(_fmt_source(value.get("source")))
    return " ".join(parts), sources


def _render_reckoning(slots: dict) -> tuple[str, list[str]]:
    parts, sources = [], []
    for item in slots.get("reckoning", []):
        change = str(item.get("change", "")).strip()
        date = str(item.get("date", "")).strip()
        body = str(item.get("body", "")).strip()
        lead = f"In {date}, " if date else ""
        actor = f"{body} " if body else ""
        parts.append(f"{lead}{actor}{change}." if actor else f"{lead}{change}.")
        if note := str(item.get("adequacy_note", "")).strip():
            parts.append(note if note.endswith(".") else note + ".")
        sources.append(_fmt_source(item.get("source")))
    return " ".join(parts), sources


RECORD_RENDERERS = {
    2: _render_archival,
    5: _render_foreknowledge,
    7: _render_timeline,
    8: _render_people,
    10: _render_aftermath,
    11: _render_reckoning,
}


# --------------------------------------------------------------------------
# Voice beats — model prompts, deliberately starved of facts
# --------------------------------------------------------------------------

def voice_prompt(beat: int, slots: dict, target_words: int) -> str:
    episode = slots.get("episode", {})
    thesis = episode.get("thesis", {})
    shared = (
        f"You are writing narration for an investigative documentary.\n"
        f"Event: {episode.get('trigger_event')} — {episode.get('place')}, "
        f"{episode.get('event_date')}.\n"
        f"Thesis: the assumed cause was {thesis.get('assumed_cause')}; the actual "
        f"cause was {thesis.get('actual_cause')}.\n\n"
        f"HARD RULES:\n"
        f"- Do NOT state any statistic, date, time, name, age or dollar figure "
        f"that is not given above. Those are supplied elsewhere.\n"
        f"- Short sentences. Fragments are welcome.\n"
        f"- No editorialising adverbs (tragically, heartbreakingly, devastatingly).\n"
        f"- Target {target_words} words.\n\n"
    )
    tasks = {
        1: ("Write the cold open. Begin with the exact date, then time of day, then "
            "place. Present tense. One sentence of situation. No branding, no greeting."),
        3: ("Write a stat burst: three to five fragments naming only the magnitudes "
            "already given to you. No verbs. If no magnitudes were given, output nothing."),
        4: ("Write the thesis turn. Pattern: the event wasn't the only threat; the "
            "true cause had been failing for a long time; and people knew. End on "
            "the fact that it was known."),
        6: ("Write the signposted background, opening with 'To understand ..., you "
            "first have to understand ...'. Explain the geography or mechanism in "
            "plain language. Translate any technical term immediately."),
        9: ("Write four standalone forward-pull sentences to close sections. Each "
            "must point forward and withhold. One per line. No numbering."),
        12: ("Write the epigram: one or two sentences inverting the premise. Pattern: "
             "not the assumed cause — the actual cause. It must invert, not summarise."),
        13: ("Write the outro. Thank viewers who watched to the end, note the work "
             "these take, ask for likes/comments/subscriptions, thank existing "
             "supporters, then a two-word sign-off and 'I'll see you in the next one.'"),
    }
    return shared + tasks.get(beat, "")


def _gemini(prompt: str) -> str:
    from google import genai

    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), contents=prompt
    )
    return (getattr(response, "text", "") or "").strip()


def build(slots: dict, target_minutes: float = 25.0,
          voice: dict[int, str] | None = None,
          use_model: bool = False) -> Script:
    """Assemble a script.

    `voice` supplies pre-written text for voice beats (used for review copies and
    when no API key is present). `use_model` generates them via Gemini instead.
    Record beats never consult either — they are formatted from slots.
    """
    result = validate(slots)
    script = Script(validation=result)
    if not result.ok:
        return script  # blocked; caller reports validation.report()

    total_words = int(target_minutes * WORDS_PER_MINUTE)
    budget = _budget(total_words)
    voice = voice or {}

    for beat in range(1, 14):
        name, _ = BEAT_PLAN[beat]
        kind = "voice" if beat in VOICE_BEATS else "record"
        out = BeatOutput(beat=beat, name=name, kind=kind, target_words=budget[beat])

        if kind == "record":
            renderer = RECORD_RENDERERS.get(beat)
            if renderer:
                out.text, out.sources = renderer(slots)
        else:
            if beat in voice:
                out.text = voice[beat]
            elif use_model:
                out.text = _gemini(voice_prompt(beat, slots, budget[beat]))

        script.beats.append(out)

    return script
