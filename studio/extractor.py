"""Deterministic structure extraction from a documentary transcript.

Everything here is measured from the text with regex and counting — no model is
involved. That is deliberate: asking an LLM to "analyse structure" returns a
plausible essay, not a measurement, and there is no way to check it. These
numbers can be checked by hand against the transcript.

The model's job comes later, in generator.py, and only for prose it is allowed
to author.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field, asdict
from typing import Any

WORDS_PER_MINUTE = 150

MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)

# --- Beat signatures -------------------------------------------------------
# Each is a construction observed across the reference corpus, not a guess.

COLD_OPEN_RE = re.compile(rf"^\W*({MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,\s+(\d{{4}})", re.I)
DATE_RE = re.compile(rf"\b({MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
# Colon form ("6:10 a.m.") plus the colon-less form transcripts produce from
# spoken audio ("By 700 a.m."), which a colon-only pattern silently drops.
CLOCK_RE = re.compile(
    r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?"
    r"|\b\d{3,4}\s*(?:a\.?m\.?|p\.?m\.?)",
    re.I,
)
ARCHIVAL_RE = re.compile(r">>\s*([^>]{10,400})")

# Three orderings occur in the corpus, and a pattern for only the first misses
# roughly half the named victims:
#   1. name → age   "Doris Comrdell, a 93-year-old woman"
#   2. name → age   "Robert Landsburg is a 48-year-old photographer"
#   3. age → name   "a 30-year-old geologist named David Johnston"
#   4. name, age,   "Samuel Barry, 20 years old, and his wife"
NAME = r"[A-Z][a-z]+(?:\s+[A-Z][a-z'\.]+){1,3}"
PERSON_PATTERNS = (
    # name ... N-year-old
    re.compile(rf"\b({NAME})\b(?:\s*,\s*|\s+(?:is|was)\s+)(?:a|an)?\s*(\d{{1,3}})\s*[-\s]?year[s]?[-\s]?old"),
    # N-year-old <role> named Name
    re.compile(rf"\b(\d{{1,3}})\s*[-\s]?year[s]?[-\s]?old\s+(?:\w+\s+){{0,3}}?named\s+({NAME})\b"),
    # Name, N,   /  Name, N years old
    re.compile(rf"\b({NAME})\s*,\s*(\d{{1,3}})\s*(?:,|years?\s+old)"),
)

MEASUREMENT_RE = re.compile(
    r"\b\d[\d,\.]*\s*(?:mph|mi|miles|ft|feet|°\s*[CF]|degrees|mbar|mibars|"
    r"acres|billion|million|thousand|percent|%|sq\s*mi|km)\b",
    re.I,
)
MONEY_RE = re.compile(r"\$\s?\d[\d,\.]*\s*(?:billion|million|trillion)?", re.I)

THESIS_MARKERS = (
    "wasn't the only", "was not the only",
    "wasn't the beginning", "was not the beginning",
    "wasn't just", "was not just",
    "didn't just", "did not just",
    "the only reason",
)
SIGNPOST_MARKERS = ("to understand", "you first have to understand", "you have to go back")
FORWARD_PULL_MARKERS = (
    "was just getting started", "what was coming", "all it needed",
    "that changed", "but something else", "it doesn't last", "it didn't last",
    "far worse than", "was about to", "had already been set in motion",
    "before dawn", "then it just stopped",
)
EPIGRAM_MARKERS = (
    "didn't destroy", "did not destroy", "didn't just", "the system did",
    "nobody taught them", "exploded sideways", "already there",
)
OUTRO_MARKERS = (
    "if you made it this far", "see you in the next one",
    "consider subscribing", "keeps these documentaries coming",
    "you're the reason", "you are the reason",
)
FOREKNOWLEDGE_MARKERS = (
    "study", "studies", "simulation", "report", "warned", "warning",
    "modeled", "modelled", "predicted", "knew it", "raising for years",
)


@dataclass
class BeatHit:
    beat: int
    name: str
    evidence: str
    position: float  # 0.0 = start of transcript, 1.0 = end

    def as_dict(self) -> dict:
        return {**asdict(self), "position": round(self.position, 3)}


@dataclass
class Analysis:
    word_count: int = 0
    estimated_runtime_minutes: float = 0.0
    sentence_count: int = 0
    mean_sentence_words: float = 0.0
    median_sentence_words: float = 0.0
    short_sentence_ratio: float = 0.0
    present_tense_signal: float = 0.0
    archival_inserts: list[str] = field(default_factory=list)
    archival_first_position: float | None = None
    clock_references: list[str] = field(default_factory=list)
    date_references: list[str] = field(default_factory=list)
    named_people: list[dict] = field(default_factory=list)
    measurements: list[str] = field(default_factory=list)
    money_references: list[str] = field(default_factory=list)
    beats: list[BeatHit] = field(default_factory=list)
    beats_missing: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["beats"] = [b.as_dict() for b in self.beats]
        return data


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _position(text: str, needle_index: int) -> float:
    return needle_index / max(1, len(text))


def _find_marker(text: str, lowered: str, markers: tuple[str, ...]) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for marker in markers:
        idx = lowered.find(marker)
        if idx != -1 and (best is None or idx < best[1]):
            end = min(len(text), idx + 160)
            best = (text[max(0, idx - 60) : end].strip(), idx)
    if best is None:
        return None
    return best[0], _position(text, int(best[1]))


def _present_tense_signal(sentences: list[str]) -> float:
    """Rough present-vs-past ratio.

    Counts third-person present markers against common past-tense endings. A
    heuristic, not a parser — reported as a signal, not a fact, because this
    format's tense discipline is worth measuring even approximately.
    """
    present = past = 0
    present_words = re.compile(
        r"\b(is|are|begins|makes|moves|reaches|arrives|continues|holds|"
        r"strikes|pushes|forms|becomes|does|has|stands|carries|sits)\b", re.I
    )
    past_words = re.compile(
        r"\b(was|were|began|made|moved|reached|arrived|continued|held|"
        r"struck|pushed|formed|became|did|had|stood|carried|sat)\b", re.I
    )
    for sentence in sentences:
        present += len(present_words.findall(sentence))
        past += len(past_words.findall(sentence))
    total = present + past
    return round(present / total, 3) if total else 0.0


# Sentence openers and place words that satisfy the capitalisation pattern but
# are never people.
_NOT_A_NAME = {
    "The", "In", "At", "By", "On", "It", "But", "And", "This", "That", "There",
    "When", "Because", "Of", "As", "From", "After", "Before", "One", "Two",
    "Hurricane", "Tropical", "Mount", "Lake", "New", "South", "North", "East", "West",
}


def _named_people(text: str) -> list[dict]:
    """Extract candidate named individuals with ages.

    Candidates only — every hit still has to be verified against a source before
    it may enter a script. See docs/FACT-SLOTS.md.
    """
    people: list[dict] = []
    seen: set[str] = set()

    for pattern in PERSON_PATTERNS:
        for match in pattern.finditer(text):
            a, b = match.group(1), match.group(2)
            # Whichever group is numeric is the age; the other is the name.
            if a.isdigit():
                age, name = a, b
            elif b.isdigit():
                age, name = b, a
            else:
                continue

            name = name.strip()
            if name.split()[0] in _NOT_A_NAME:
                continue
            if not 1 <= int(age) <= 120:
                continue

            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            people.append({
                "name": name,
                "age": int(age),
                "position": round(_position(text, match.start()), 3),
                "verified": False,
                "source": "",
            })

    return sorted(people, key=lambda p: p["position"])


def analyse(text: str) -> Analysis:
    """Measure one transcript against the reference architecture."""
    text = text.strip()
    lowered = text.lower()
    sentences = _sentences(text)
    lengths = [len(s.split()) for s in sentences] or [0]

    a = Analysis()
    a.word_count = len(text.split())
    a.estimated_runtime_minutes = round(a.word_count / WORDS_PER_MINUTE, 1)
    a.sentence_count = len(sentences)
    a.mean_sentence_words = round(statistics.mean(lengths), 1)
    a.median_sentence_words = round(statistics.median(lengths), 1)
    a.short_sentence_ratio = round(sum(1 for n in lengths if n < 6) / max(1, len(lengths)), 3)
    a.present_tense_signal = _present_tense_signal(sentences)

    a.archival_inserts = [m.group(1).strip()[:200] for m in ARCHIVAL_RE.finditer(text)]
    first_archival = ARCHIVAL_RE.search(text)
    if first_archival:
        a.archival_first_position = round(_position(text, first_archival.start()), 3)

    a.clock_references = [m.group(0) for m in CLOCK_RE.finditer(text)]
    a.date_references = sorted({m.group(0) for m in DATE_RE.finditer(text)})
    a.named_people = _named_people(text)
    a.measurements = [m.group(0).strip() for m in MEASUREMENT_RE.finditer(text)]
    a.money_references = [m.group(0).strip() for m in MONEY_RE.finditer(text)]

    # --- Beat detection ----------------------------------------------------
    beats: list[BeatHit] = []

    if COLD_OPEN_RE.match(text):
        beats.append(BeatHit(1, "Cold open (date-first, present tense)",
                             text[:120].strip(), 0.0))

    if a.archival_inserts:
        beats.append(BeatHit(2, "Archival audio insert",
                             a.archival_inserts[0][:120],
                             a.archival_first_position or 0.0))

    if a.measurements:
        beats.append(BeatHit(3, "Stat burst", ", ".join(a.measurements[:4]), 0.05))

    if hit := _find_marker(text, lowered, THESIS_MARKERS):
        beats.append(BeatHit(4, "Thesis turn", hit[0], hit[1]))

    fore = sum(lowered.count(m) for m in FOREKNOWLEDGE_MARKERS)
    if fore >= 3:
        beats.append(BeatHit(5, "Foreknowledge / ignored warnings",
                             f"{fore} foreknowledge markers", 0.2))

    if hit := _find_marker(text, lowered, SIGNPOST_MARKERS):
        beats.append(BeatHit(6, "Signposted background", hit[0], hit[1]))

    if len(a.clock_references) >= 4:
        beats.append(BeatHit(7, "Timestamped escalation",
                             f"{len(a.clock_references)} clock references", 0.4))

    if a.named_people:
        beats.append(BeatHit(8, f"Named people ×{len(a.named_people)}",
                             ", ".join(f"{p['name']} ({p['age']})" for p in a.named_people[:4]),
                             statistics.mean([p["position"] for p in a.named_people])))

    pulls = [m for m in FORWARD_PULL_MARKERS if m in lowered]
    if pulls:
        beats.append(BeatHit(9, f"Forward-pull closers ×{len(pulls)}",
                             "; ".join(pulls[:4]), 0.5))

    if a.money_references or len(a.measurements) > 8:
        beats.append(BeatHit(10, "Aftermath numbers",
                             ", ".join(a.money_references[:3]) or "measurement-dense", 0.8))

    if any(w in lowered for w in ("acknowledges", "concludes", "commits", "established",
                                  "retired by", "investigation concluded", "training materials")):
        beats.append(BeatHit(11, "Institutional reckoning", "reckoning language present", 0.85))

    tail_start = int(len(text) * 0.82)
    tail, tail_lower = text[tail_start:], lowered[tail_start:]
    if hit := _find_marker(tail, tail_lower, EPIGRAM_MARKERS):
        beats.append(BeatHit(12, "Epigram (thesis inverted)", hit[0],
                             0.82 + hit[1] * 0.18))

    if hit := _find_marker(tail, tail_lower, OUTRO_MARKERS):
        beats.append(BeatHit(13, "Outro", hit[0], 0.82 + hit[1] * 0.18))

    a.beats = sorted(beats, key=lambda b: b.beat)
    found = {b.beat for b in beats}
    a.beats_missing = [n for n in range(1, 14) if n not in found]
    return a


def compare(analyses: dict[str, Analysis]) -> dict[str, Any]:
    """Aggregate several transcripts into a corpus profile.

    A beat present in every sample is an invariant of the format; one present in
    a minority is that episode's flourish. Only the former is safe to template.
    """
    if not analyses:
        return {}

    counts: dict[int, int] = {}
    for a in analyses.values():
        for beat in a.beats:
            counts[beat.beat] = counts.get(beat.beat, 0) + 1

    n = len(analyses)
    return {
        "sample_size": n,
        "words": {
            "min": min(a.word_count for a in analyses.values()),
            "max": max(a.word_count for a in analyses.values()),
            "mean": round(statistics.mean([a.word_count for a in analyses.values()])),
        },
        "runtime_minutes": {
            "min": min(a.estimated_runtime_minutes for a in analyses.values()),
            "max": max(a.estimated_runtime_minutes for a in analyses.values()),
        },
        "mean_sentence_words": round(
            statistics.mean([a.mean_sentence_words for a in analyses.values()]), 1
        ),
        "short_sentence_ratio": round(
            statistics.mean([a.short_sentence_ratio for a in analyses.values()]), 3
        ),
        "present_tense_signal": round(
            statistics.mean([a.present_tense_signal for a in analyses.values()]), 3
        ),
        "named_people_per_episode": round(
            statistics.mean([len(a.named_people) for a in analyses.values()]), 1
        ),
        "beat_frequency": {
            str(beat): f"{counts.get(beat, 0)}/{n}" for beat in range(1, 14)
        },
        "invariant_beats": sorted(b for b, c in counts.items() if c == n),
        "optional_beats": sorted(b for b, c in counts.items() if 0 < c < n),
    }
