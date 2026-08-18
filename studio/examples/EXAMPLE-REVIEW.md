# Worked example — review notes

**Topic:** Buffalo Creek, Logan County, West Virginia, 26 February 1972.
**Output:** `out/buffalo_creek_1972.mp4` — 12m28s, 1920×1080, h264 + AAC.

Chosen because it is the closest structural analogue to your reference corpus: a
"flood" that dissolves on inspection into documented negligence. It clears all
four ideation gates — a thesis exists, the event is 54 years old, official
inquiry material exists, and named individuals are on the record.

---

## ⚠️ Not publishable as-is. Two reasons.

**1. Two gates are simulated.** In real use these are your actions:

| Gate | State | What you must do |
|---|---|---|
| `people[*].family_sensitivity_reviewed` | simulated | Genuinely review both entries |
| `archival_audio[0]` | simulated | Locate a real clip and establish rights |

Run the validator unmodified and it blocks with 4 findings. That block is the
system working.

**2. Sources are secondary.** Every primary document — the Governor's Ad Hoc
Commission report, the Bureau of Mines inspection record — was **egress-blocked
from the build environment**. Citations therefore rest on search summaries and
encyclopedia entries, mostly Tier C corroborated by an ASDSO case study.

**Before publishing, every figure must be checked against the primary record.**
My source grading is a research starting point, not verification.

---

## Growth across three passes

| Pass | Words | Runtime | What changed |
|---|---|---|---|
| 1 | 845 | 5m34s | Initial research |
| 2 | 1,492 | 9m54s | Deeper research: 13 timeline entries, 4 foreknowledge, 2 people |
| 3 | **2,020** | **12m28s** | Authored narration attached to each sourced fact |

Against a 25-minute target the shortfall is 1,730 words, and the tool names
exactly where:

| Beat | Words | Target | Gap |
|---|---|---|---|
| 7 Timestamped escalation | 473 | 1050 | **−577** |
| 8 Named people | 271 | 750 | **−479** |
| 10 Aftermath | 121 | 300 | −179 |
| 11 Reckoning | 206 | 349 | −143 |
| 6 Background | 340 | 476 | −136 |
| 1 Cold open | 84 | 75 | **+9 ok** |
| 4 Thesis | 99 | 101 | **−2 ok** |
| 12 Epigram | 26 | 30 | **−4 ok** |

Voice beats hit target. Record beats carry the entire deficit. Prose is cheap;
sourced fact is expensive.

**To reach 25 minutes:** roughly 12 more timeline entries and 2 more named
individuals, each with a citation.

---

## The strongest fact the research turned up

The thesis is no longer "residents weren't warned." It is worse than that:

> The water had been rising for two days. A company vice president and the police
> were both told. In the last hours before it broke, **the vice president ordered
> every effort to warn residents stopped** and told police the dam would hold.

And separately: the only plan that ever existed for Impoundment 3 — holding 132
million gallons above seventeen inhabited communities — **was a sketch drawn by
the on-site vice president.**

One restraint worth noting: sources describe "a vice president" who stopped the
warnings, and separately name Steve Dasovich as the vice president who drew the
sketch. **I did not merge them.** They may be the same man; nothing I could
reach says so. The script keeps them separate.

---

## Known weaknesses

- **Beat 8 is two people, not 3–4.** The validator warns. This is the biggest
  quality gap and it is a sourcing problem, not a writing one.
- **Beat 2 is a placeholder.** No archival audio sourced or cleared.
- **Voice is espeak-ng** and sounds like 1990s synthesis. `translate.google.com`
  and `huggingface.co` are both blocked here, so gTTS and Kokoro cannot run.
  Kokoro on your machine is a completely different result.
- **The middle 60% of frame is empty.** Procedural gradients are a placeholder
  for footage, not a solution.
- `age: null` on both people — not in my sources, so left null rather than
  guessed. That is the contract working.

## What to judge

1. **Structure** — does the beat order hold attention for 12 minutes?
2. **The thesis turn (beat 4)** and **epigram (beat 12)** — did the format transfer?
3. **Caption pacing** — one caption per sentence, held for its own audio.

Ignore the voice and the backdrops. Both are known placeholders with known fixes.
