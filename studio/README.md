# Documentary Studio

Localhost tool: paste transcripts → measure their structure → validate researched
facts → assemble a script.

```bash
python studio/server.py
# open http://127.0.0.1:8765
```

**Standard library only.** Nothing to install. Gemini is optional and used only
for voice beats; structure extraction, validation and assembly are local and
deterministic.

Binds to `127.0.0.1` on purpose — none of this is hardened for network exposure,
and slot documents hold unpublished research.

---

## The three tabs

**1 · Analyse** — paste one or more transcripts. Reports word count, estimated
runtime, sentence length, present-tense signal, archival clips, clock references,
candidate named people, and which of the 13 beats it detected with positions.

Measurement is **regex and counting, not a model**. Asking an LLM to "analyse
structure" returns a plausible essay you cannot check. Every number here can be
verified by hand against the text.

**2 · Facts** — paste or load a slot document, then validate. Missing sources
**block**; they are not warnings.

**3 · Script** — assemble. Record beats render from slots by formatting; voice
beats come from the supplied text or from Gemini. The beat table shows word drift
against target so an under-researched episode is visible immediately.

---

## Files

| | |
|---|---|
| `extractor.py` | Deterministic structure measurement |
| `schema.py` | Fact-slot validation — the render gate |
| `generator.py` | Beat assembly; voice prompts |
| `server.py` | Localhost HTTP server |
| `index.html` | Single-page UI |
| `corpus/` | Reference transcripts (gitignored — third-party content) |
| `corpus_profile.json` | Derived structural profile, committed |
| `examples/` | Worked example — start with `EXAMPLE-REVIEW.md` |

Specifications live in `docs/SCRIPT-ARCHITECTURE.md` and `docs/FACT-SLOTS.md`.

---

## Why record and voice beats are separated

The generator cannot invent a death toll because it is never asked to write one.

Voice beats (1, 3, 4, 6, 9, 12, 13) receive a prompt containing the thesis and
explicit instructions not to state any figure, date, name or age. Record beats
(2, 5, 7, 8, 10, 11) never reach a model at all — they are string formatting over
validated slots.

That is a structural guarantee rather than an instruction a model may ignore.

---

## Optional: Gemini for voice beats

```bash
export GOOGLE_API_KEY=...     # aistudio.google.com/apikey
```

Free tier allows 1,500 requests/day; one episode uses seven. Without a key,
write the voice beats yourself — the worked example does exactly that.

---

## Verified behaviour

Both modules were tested against the reference transcripts rather than assumed:

- The extractor finds **13/13 beats** in the Katrina transcript and all four
  named individuals in Mount St. Helens. Two detection bugs surfaced during that
  check: a name-then-age-only regex that missed *"a 30-year-old geologist named
  David Johnston"*, and a colon-only clock pattern that dropped *"By 700 a.m."*
  Both fixed.
- The validator blocks all eleven violation classes: missing source, bare-string
  source, Tier D, uncorroborated Tier C, incomplete source, wrong tier for a
  named decedent, unreviewed sensitivity flag, non-verbatim final words, absent
  archival audio, missing thesis, implausible age.
- Beat shares sum to exactly 1.0.
