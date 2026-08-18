"""Fact-slot validation — the gate between research and script.

Implements the contract in docs/FACT-SLOTS.md. The rule this file exists to
enforce: a fact-bearing field without a source does not render. Not a warning,
not a placeholder in the output — a hard failure, because a warning in a log is
not a defence when the claim is about a named person who died.

Beats 1, 3, 4, 6, 9, 12, 13 are voice and carry no facts. Beats 5, 7, 8, 10, 11
are record and every one of their fields passes through here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

MIN_EVENT_AGE_YEARS = 10  # ideation gate 3
MIN_NAMED_PEOPLE = 3      # ideation gate 2


class Tier(str, Enum):
    """Source grades. D is barred outright."""

    A = "A"  # official report, agency record, peer-reviewed, court document
    B = "B"  # contemporaneous major-outlet reporting
    C = "C"  # retrospective journalism, documentary, encyclopedia
    D = "D"  # forum, blog, aggregator, social post, AI output


TIER_ALLOWED = {Tier.A, Tier.B, Tier.C}
TIER_FOR_NAMED_DECEDENT = {Tier.A}

# A source needs a body, a title, a date and a locator — a bare URL is not one.
SOURCE_MIN_FIELDS = ("body", "title", "date", "locator")


class Severity(str, Enum):
    BLOCK = "block"
    WARN = "warn"


@dataclass
class Finding:
    severity: Severity
    path: str
    message: str

    def __str__(self) -> str:
        mark = "✗" if self.severity is Severity.BLOCK else "⚠"
        return f"{mark} {self.path}: {self.message}"


@dataclass
class ValidationResult:
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocks(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.BLOCK]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARN]

    @property
    def ok(self) -> bool:
        return not self.blocks

    def block(self, path: str, message: str) -> None:
        self.findings.append(Finding(Severity.BLOCK, path, message))

    def warn(self, path: str, message: str) -> None:
        self.findings.append(Finding(Severity.WARN, path, message))

    def report(self) -> str:
        if not self.findings:
            return "✅ All fact slots sourced and within contract."
        lines = [str(f) for f in self.findings]
        verdict = "✅ RENDER ALLOWED" if self.ok else f"❌ RENDER BLOCKED ({len(self.blocks)} blocking)"
        return "\n".join(lines + ["", verdict])


def _check_source(result: ValidationResult, path: str, source: Any,
                  required_tiers: set[Tier] | None = None) -> Tier | None:
    """Validate one source object. Returns its tier when acceptable."""
    if not source:
        result.block(path, "missing source — unsourced claims cannot render")
        return None
    if isinstance(source, str):
        result.block(
            path,
            "source is a bare string; needs body, title, date and locator",
        )
        return None
    if not isinstance(source, dict):
        result.block(path, f"source must be an object, got {type(source).__name__}")
        return None

    missing = [f for f in SOURCE_MIN_FIELDS if not str(source.get(f, "")).strip()]
    if missing:
        result.block(path, f"source incomplete — missing {', '.join(missing)}")
        return None

    raw_tier = str(source.get("tier", "")).strip().upper()
    try:
        tier = Tier(raw_tier)
    except ValueError:
        result.block(path, f"source tier {raw_tier!r} invalid; expected A, B, C or D")
        return None

    if tier is Tier.D:
        result.block(path, "Tier D source (forum/blog/AI output) is barred outright")
        return None

    if required_tiers and tier not in required_tiers:
        allowed = "/".join(sorted(t.value for t in required_tiers))
        result.block(path, f"needs Tier {allowed}, got Tier {tier.value}")
        return None

    if tier is Tier.C and not source.get("corroborated_by"):
        result.block(path, "Tier C source requires corroborated_by (a Tier A or B source)")
        return None

    return tier


def _validate_people(result: ValidationResult, people: list) -> None:
    """Named individuals — the strictest rules in the contract."""
    if not isinstance(people, list) or not people:
        result.block("people", "beat 8 requires at least one named individual")
        return

    if len(people) < MIN_NAMED_PEOPLE:
        result.warn(
            "people",
            f"{len(people)} named — the corpus averages 3-4; a thin beat 8 weakens the episode",
        )

    for i, person in enumerate(people):
        path = f"people[{i}]"
        if not isinstance(person, dict):
            result.block(path, "must be an object")
            continue

        name = str(person.get("full_name", "")).strip()
        if not name:
            result.block(path, "full_name is required")
        elif len(name.split()) < 2:
            result.warn(f"{path}.full_name", f"{name!r} looks partial — do not complete it yourself")

        age = person.get("age")
        if age is not None and not (isinstance(age, int) and 0 < age <= 120):
            result.block(f"{path}.age", f"implausible age {age!r}")

        if not str(person.get("outcome_line", "")).strip():
            result.block(f"{path}.outcome_line", "required — the flat outcome line is the beat")
        else:
            _check_editorialising(result, f"{path}.outcome_line", person["outcome_line"])

        # Three categories, three evidentiary burdens.
        #
        #   decedent — a death attributed to a named person. Tier A only.
        #   survivor — a private individual. Any allowed tier, but they must have
        #              spoken publicly on the record; otherwise use their role.
        #   official — a person named in an official inquiry or agency record in
        #              their professional capacity. Naming them is ordinary
        #              journalism, but the official record itself must be the
        #              source, so Tier A.
        #
        # The third category emerged from real use: an executive named in a state
        # commission's findings is neither a decedent nor a private survivor, and
        # requiring them to have "spoken publicly" would have barred a fact that
        # a government report states outright.
        role_type = str(person.get("role_type", "")).strip().lower()
        if not role_type:
            role_type = "decedent" if person.get("decedent", True) else "survivor"

        if role_type not in {"decedent", "survivor", "official"}:
            result.block(f"{path}.role_type",
                         f"{role_type!r} invalid; expected decedent, survivor or official")
        elif role_type == "decedent":
            _check_source(result, f"{path}.source", person.get("source"),
                          TIER_FOR_NAMED_DECEDENT)
        elif role_type == "official":
            _check_source(result, f"{path}.source", person.get("source"),
                          TIER_FOR_NAMED_DECEDENT)
            if not str(person.get("official_capacity", "")).strip():
                result.block(f"{path}.official_capacity",
                             "required — state the role the official record names them in")
        else:  # survivor
            _check_source(result, f"{path}.source", person.get("source"))
            if not person.get("spoke_publicly_on_record", False):
                result.block(
                    f"{path}.spoke_publicly_on_record",
                    "a living person may only be named if they have spoken publicly "
                    "on the record; otherwise use their role",
                )

        is_decedent = role_type == "decedent"

        if person.get("final_words"):
            if not is_decedent:
                result.warn(f"{path}.final_words", "final_words on a survivor — is decedent flag correct?")
            if not person.get("final_words_verbatim", False):
                result.block(
                    f"{path}.final_words",
                    "must be flagged final_words_verbatim — never paraphrase into quotation marks",
                )
            _check_source(result, f"{path}.final_words_source",
                          person.get("final_words_source"),
                          TIER_FOR_NAMED_DECEDENT if is_decedent else None)

        if not person.get("family_sensitivity_reviewed", False):
            result.block(
                f"{path}.family_sensitivity_reviewed",
                "a human must review this entry before render",
            )


EDITORIALISING = re.compile(
    r"\b(tragically|heartbreaking(?:ly)?|sadly|horrifying(?:ly)?|senseless(?:ly)?|"
    r"devastating(?:ly)?|shockingly|cruel(?:ly)?|needless(?:ly)?)\b",
    re.I,
)


def _check_editorialising(result: ValidationResult, path: str, text: str) -> None:
    """The outcome line's power is its flatness. Adverbs undo it."""
    if found := EDITORIALISING.findall(text or ""):
        result.warn(path, f"editorialising ({', '.join(set(w.lower() for w in found))}) — keep it flat")


def _validate_sourced_list(result: ValidationResult, items: Any, key: str,
                           required: tuple[str, ...]) -> None:
    if not isinstance(items, list) or not items:
        result.block(key, "required and must be non-empty")
        return
    for i, item in enumerate(items):
        path = f"{key}[{i}]"
        if not isinstance(item, dict):
            result.block(path, "must be an object")
            continue
        for req in required:
            if not str(item.get(req, "")).strip():
                result.block(f"{path}.{req}", "required")
        _check_source(result, f"{path}.source", item.get("source"))


def validate(doc: dict) -> ValidationResult:
    """Validate a complete episode slot document."""
    result = ValidationResult()

    if not isinstance(doc, dict):
        result.block("$", "episode document must be an object")
        return result

    episode = doc.get("episode")
    if not isinstance(episode, dict):
        result.block("episode", "required")
    else:
        for req in ("event_date", "place", "trigger_event"):
            if not str(episode.get(req, "")).strip():
                result.block(f"episode.{req}", "required")

        thesis = episode.get("thesis")
        if not isinstance(thesis, dict):
            result.block("episode.thesis", "required — no thesis means no beat 4")
        else:
            for req in ("assumed_cause", "actual_cause"):
                if not str(thesis.get(req, "")).strip():
                    result.block(f"episode.thesis.{req}", "required")
            _check_source(result, "episode.thesis.source", thesis.get("source"))

    _validate_sourced_list(result, doc.get("foreknowledge"), "foreknowledge",
                           ("document_name", "prediction"))
    _validate_sourced_list(result, doc.get("timeline"), "timeline",
                           ("timestamp_local", "event"))
    _validate_people(result, doc.get("people"))
    _validate_sourced_list(result, doc.get("reckoning"), "reckoning", ("change",))

    aftermath = doc.get("aftermath")
    if not isinstance(aftermath, dict) or not aftermath:
        result.block("aftermath", "required — beat 10 needs figures")
    else:
        for key, value in aftermath.items():
            # `narration` is authored prose covering the whole block, not a
            # figure, so it carries no value/source pair of its own — the
            # figures it describes are each validated below.
            if key == "narration":
                continue
            if not isinstance(value, dict):
                result.block(f"aftermath.{key}", "must be an object with value and source")
                continue
            if value.get("value") in (None, ""):
                continue  # a genuinely unknown figure may be omitted
            _check_source(result, f"aftermath.{key}.source", value.get("source"))

    archival = doc.get("archival_audio")
    if not isinstance(archival, list) or not archival:
        result.block("archival_audio", "beat 2 requires at least one real recorded clip")
    else:
        for i, clip in enumerate(archival):
            path = f"archival_audio[{i}]"
            if not isinstance(clip, dict):
                result.block(path, "must be an object")
                continue
            if not str(clip.get("rights_basis", "")).strip():
                result.block(f"{path}.rights_basis", "required before this clip may be used")
            _check_source(result, f"{path}.source", clip.get("source"))

    return result


def gate_candidate(candidate: dict) -> ValidationResult:
    """Apply the four ideation gates from docs/FACT-SLOTS.md."""
    result = ValidationResult()

    gate1 = candidate.get("gate_1_thesis") or {}
    if not gate1.get("pass"):
        result.block("gate_1_thesis", "no documented-and-ignored institutional failure — reject")
    elif not str(gate1.get("source", "")).strip():
        result.block("gate_1_thesis.source", "gate 1 cannot pass without a citation")

    gate2 = candidate.get("gate_2_source_density") or {}
    for key in ("timeline", "aftermath", "reckoning"):
        if not gate2.get(key):
            result.block(f"gate_2_source_density.{key}", "no sourceable material")
    named = gate2.get("named_people", 0)
    if not isinstance(named, int) or named < MIN_NAMED_PEOPLE:
        result.block(
            "gate_2_source_density.named_people",
            f"{named} sourceable named individuals; beat 8 needs {MIN_NAMED_PEOPLE}+",
        )

    age = candidate.get("gate_3_age_years", 0)
    if not isinstance(age, int) or age < MIN_EVENT_AGE_YEARS:
        result.warn(
            "gate_3_age_years",
            f"event is {age} years old; under {MIN_EVENT_AGE_YEARS} means unsettled facts "
            "and reachable grieving families",
        )

    gate4 = candidate.get("gate_4_archival_audio") or {}
    if not gate4.get("available"):
        result.block("gate_4_archival_audio", "no archival audio — beat 2 cannot be built")
    elif not str(gate4.get("rights_basis", "")).strip():
        result.block("gate_4_archival_audio.rights_basis", "required")

    return result
