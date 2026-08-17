# Worked example — review notes

**Topic:** The Buffalo Creek flood, Logan County, West Virginia, 26 February 1972.

Chosen because it is the closest structural analogue to your reference corpus: a
"flood" that dissolves on inspection into documented corporate negligence. It
clears all four ideation gates — there is a thesis, the event is 54 years old,
official inquiry material exists, and named individuals are on the record.

---

## ⚠️ This example is NOT publishable. Read this section first.

Two gates were **simulated** to produce a readable script. In real use they are
your actions, not mine:

| Gate | State | What you must actually do |
|---|---|---|
| `people[0].family_sensitivity_reviewed` | **simulated true** | Genuinely review the entry. Shirley Marcum is a living person. |
| `archival_audio[0]` | **simulated** | Locate a real clip and establish a rights basis. The slot file has it as an explicit `PLACEHOLDER` with `source: null`. |

Run the validator on the unmodified file and it **blocks**:

```
✗ people[0].family_sensitivity_reviewed: a human must review this entry before render
✗ archival_audio[0].rights_basis: required before this clip may be used
✗ archival_audio[0].source: missing source — unsourced claims cannot render
❌ RENDER BLOCKED (3 blocking)
```

That block is the system working. It is the thing I most want you to examine.

---

## The number that matters: 845 words, not 3,750

The script assembled to **845 words ≈ 5.6 minutes** against a 25-minute target.
The shortfall is not a bug — it is an accurate measurement of how much research
is missing, and it points at exactly where:

| Beat | Produced | Target | Gap | Why |
|---|---|---|---|---|
| 7 Timestamped escalation | 89w | 1050w | **−961** | 3 timeline entries; needs ~25–30 |
| 8 Named people | 66w | 750w | **−684** | 1 person; needs 3–4 |
| 10 Aftermath numbers | 12w | 300w | −288 | 3 figures; needs damage, structures, population |
| 11 Institutional reckoning | 85w | 349w | −264 | needs the legislative aftermath |
| 5 Foreknowledge | 75w | 300w | −225 | needs the inspection record in detail |
| 6 Background | 240w | 476w | −236 | expand the slurry-impoundment explanation |

**Voice beats came in close to target** (thesis −23, epigram −14). The deficit is
entirely in the record beats. That is the honest shape of this problem: prose is
cheap, sourced fact is expensive.

To reach 25 minutes you need roughly **25 more timeline entries and 3 more named
people**, each with a citation. That is an afternoon in an archive, not a prompt.

---

## What is genuinely sourced here

Every figure traces to a cited source in the slot file:

- 132 million gallons; ~08:00, 26 Feb 1972; Middle Fork of Buffalo Creek
- Two further waste dams breached within ~2 minutes
- 17 communities destroyed over ~3 hours (all named)
- 125 dead · 1,121 injured · 4,000+ homeless
- Dam 3 declared *satisfactory* by a federal inspector **four days earlier**
- Pittston knew the water was rising ~24 hours ahead; residents were not told
- Ad Hoc Commission of Inquiry: 8 hearings, 91 witnesses, 9 volumes, finding of
  *"flagrant disregard"*
- 645 plaintiffs; settled 1974 for $13.5M ≈ $13,000 each after fees
- Shirley Marcum's warning, quoted verbatim

**Source-tier caveat you should not skip:** most slots are Tier C corroborated by
an ASDSO case study marked Tier A. Before publishing, replace the Tier C entries
with the primary documents — the Commission report itself, and the Bureau of
Mines inspection record. My grading is a research starting point, not a
verification.

---

## What to examine in the output

1. **`out/buffalo_creek_annotated.md`** — beat markers, word counts, per-beat
   sources. Read this to judge whether the *structure* landed.
2. **`out/buffalo_creek_narration.txt`** — clean text, TTS-ready. Read this aloud
   to judge whether it *sounds* like the reference channel.
3. The **epigram** (beat 12) is the test of whether the format transferred:
   > *"The rain didn't destroy Buffalo Creek. It just found out what Pittston had built above it."*
   Compare to the corpus pattern — `not {assumed cause} — {actual cause}`.

## Known weaknesses, stated plainly

- **Beat 8 is one person.** The corpus averages 3–4. The validator warns about
  this and it is the single biggest quality gap.
- **Beat 2 is a placeholder.** No archival audio has been sourced or cleared.
- **`age: null` on the only person.** Marcum's age isn't in my sources, so it is
  left null rather than guessed. That is the contract working.
- The reckoning omits the legislative aftermath (dam-safety legislation) because
  I could not source it to the standard the schema demands.
