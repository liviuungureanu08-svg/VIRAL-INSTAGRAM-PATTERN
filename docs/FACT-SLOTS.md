# Fact Slots — the verified-input contract

Companion to `SCRIPT-ARCHITECTURE.md`. That document defines the *shape* of an
episode. This one defines where its *facts* are allowed to come from.

---

## The problem, stated precisely

The emotional engine of this format is beat 8 — named victim stories:

> *Doris Comrdell, a 93-year-old woman from Chalmette in St. Bernard Parish, is
> rescued after several days trapped in her flooded home… She never returned.*

That sentence contains a full name, an age, a parish, a duration, and a fate.
Ask a language model to write it and it will produce something exactly as
specific, exactly as fluent, and **possibly entirely invented** — about a real
person who really died, whose family is alive and searchable.

The same exposure runs through:

| Beat | Hallucination-prone content |
|---|---|
| 5 | Study names, dates, agencies, quotes about being dismissed |
| 7 | Clock times to the minute, wind speeds, pressures, sequence of failures |
| 8 | **Names, ages, roles, relationships, final words, outcomes** |
| 10 | Death tolls, dollar figures, structure counts, population change |
| 11 | Official admissions, journal citations, budget figures |

These are not decoration. They are the credibility of the channel. Beats 1–4,
6, 9, 12 and 13 are *voice*, and a model can write them. Beats 5, 7, 8, 10, 11
are *record*, and a model must never author them.

**The generator's contract: arrange facts it was given. Never supply them.**

---

## Slot schema

Every fact-bearing field is a slot with a value **and** a source. A slot with no
source does not render — the script builder fails loudly rather than emitting an
unsourced claim.

```json
{
  "episode": {
    "title_working": "",
    "event_date": "1980-05-18",
    "event_time_local": "08:32",
    "place": "Mount St. Helens, Skamania County, Washington",
    "trigger_event": "Lateral volcanic blast",
    "thesis": {
      "assumed_cause": "The eruption",
      "actual_cause": "A restricted zone drawn by politics rather than science",
      "duration_of_failure": "2 months of ignored warnings",
      "who_knew": "USGS geologists monitoring the bulge",
      "source": ""
    }
  },

  "foreknowledge": [
    {
      "document_name": "Hurricane Pam exercise",
      "date": "2004-07",
      "commissioning_body": "FEMA",
      "prediction": "Tens of thousands of deaths; city submerged",
      "response": "Findings not acted upon",
      "quote": "there were a lot of federal folks who were just in the back room laughing",
      "quote_attribution": "",
      "source": ""
    }
  ],

  "timeline": [
    {
      "timestamp_local": "1980-05-18T08:32:11",
      "event": "Magnitude 5.1 earthquake beneath the north flank",
      "measurement": { "value": 5.1, "unit": "Mw" },
      "source": ""
    }
  ],

  "people": [
    {
      "full_name": "David Johnston",
      "age": 30,
      "role": "USGS volcanologist",
      "location": "Coldwater II observation post, 6 mi north of summit",
      "humanising_detail": "Had taken the shift 13 hours earlier, covering for a colleague",
      "final_words": "Vancouver, Vancouver, this is it",
      "outcome": "Body never found",
      "outcome_line": "David Johnston's body is never found.",
      "source": "",
      "family_sensitivity_reviewed": false
    }
  ],

  "aftermath": {
    "death_toll": { "value": 57, "revising_body": "USGS", "source": "" },
    "damage_usd": { "value": 1100000000, "year_basis": 1980, "source": "" },
    "structures_destroyed": { "value": null, "source": "" },
    "area_affected": { "value": 230, "unit": "sq mi", "source": "" },
    "population_change": { "before": null, "after": null, "source": "" }
  },

  "reckoning": [
    {
      "change": "Cascades Volcano Observatory established",
      "date": "1982",
      "body": "USGS",
      "adequacy_note": "",
      "source": ""
    }
  ],

  "archival_audio": [
    {
      "description": "News anchor, day of eruption",
      "transcript": "it looked like the start of World War III",
      "rights_basis": "",
      "source": ""
    }
  ]
}
```

### Source field requirements

A `source` is not a URL alone. Minimum: **publication or body, title, date, and
locator** (URL, page, or archive reference).

---

## Verification tiers

| Tier | Meaning | Allowed in script |
|---|---|---|
| **A** | Official report, agency record, peer-reviewed paper, court document | ✅ Yes |
| **B** | Contemporaneous major-outlet reporting | ✅ Yes |
| **C** | Retrospective journalism, documentary, encyclopedia | ⚠️ Corroborate with A or B |
| **D** | Forum, blog, aggregator, social post, AI output | ❌ Never |

**Names, ages and final words require Tier A or two independent Tier B sources.**
Nothing else in the schema is as consequential to get wrong.

### Named-decedent rules

1. Full name, age, and manner of death: **Tier A, or two independent Tier B**.
2. Final words / final transmissions: **quoted from a source, verbatim**. Never paraphrased into quotation marks, never reconstructed.
3. `family_sensitivity_reviewed` must be set true by a human before render.
4. If a person's name appears in sources only as a partial or nickname, use exactly that. Do not complete it.
5. Living survivors described in distressing circumstances: prefer role over name unless they have spoken publicly on the record.

---

## Ideation pipeline — generating new episode candidates

The user's aim is new episodes, not rewrites. Ideation is a *filter*, not a
creative act: the tool proposes real documented events, then gates them.

```
domain input → candidate events → gate 1..4 → sourcing brief → slot filling → script
```

### Gate 1 — Thesis test *(hard gate)*
Is there an institutional failure that was **documented in advance and ignored**?
Without it there is no beat 4, and without beat 4 the format collapses. Reject.

### Gate 2 — Source density
Does Tier A/B material exist for: a minute-level timeline, an aftermath figure
set, an official reckoning, **and at least three named individuals**? If the
victim stories cannot be sourced, the episode cannot be made honestly.

### Gate 3 — Recency and sensitivity
Very recent events mean unresolved facts, active litigation, and grieving
families reachable by comment section. Prefer events **10+ years old**, where an
official report exists. All five reference episodes clear this: 1980, 2005, 2008,
2017, 2018.

### Gate 4 — Archival audio availability
Beat 2 needs real recorded audio with a usable rights basis. Check before
committing to a topic.

### Candidate record

```json
{
  "candidate": "",
  "event_date": "",
  "trigger": "",
  "proposed_thesis": { "assumed_cause": "", "actual_cause": "" },
  "gate_1_thesis": { "pass": false, "evidence": "", "source": "" },
  "gate_2_source_density": { "timeline": false, "aftermath": false, "reckoning": false, "named_people": 0 },
  "gate_3_age_years": 0,
  "gate_4_archival_audio": { "available": false, "rights_basis": "" },
  "verdict": "reject | research | greenlight"
}
```

An LLM may **propose** candidates and **draft** the thesis. It may not mark any
gate as passed. Gates are set by a human or by a retrieval step that returns a
citation.

---

## Division of labour

| Component | May be model-generated |
|---|---|
| Beats 1, 3, 4, 6, 9, 12, 13 — voice, framing, transitions | ✅ Yes |
| Beat 2 selection — which real clip, where | ⚠️ Proposes; human confirms rights |
| Beats 5, 7, 10, 11 — documents, times, figures, reckoning | ❌ Extracted from sources only |
| Beat 8 — named people | ❌ **Extracted only. Never generated.** |
| Candidate ideation | ✅ Proposes; ❌ cannot self-approve gates |

## Builder behaviour

- A slot missing `source` → **hard failure**, not a warning.
- A `people[]` entry with `family_sensitivity_reviewed: false` → **blocks render**.
- Any Tier D source anywhere → **blocks render**.
- Word-count targets from `SCRIPT-ARCHITECTURE.md` are advisory; source
  completeness is not.

This is the difference between a documentary channel and a liability.
