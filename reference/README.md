# Reference videos

Style analysis lives here — the "copy the format, change the content" half of
the pipeline.

## Why fetching and analysing are separate

The environment that reads this repo has **no network route to YouTube**. So the
work is split:

| Step | Runs where | Produces |
|---|---|---|
| `fetch_reference.py` | A GitHub runner, or your own machine | `source.mp4`, `metadata.json`, `transcript.txt` |
| `analyze_video.py` | Anywhere, offline | `analysis.json`, `REPORT.md`, `contact_sheet.jpg`, `frames/` |

Only the second step's output is committed. `source.mp4` is gitignored — it is
large, and it is someone else's copyrighted work.

## The easy path

Actions → **Analyze Reference Video** → Run workflow → paste the URL.

The runner fetches, analyses, commits the artifacts back, and prints the report
into the run summary. Nothing to install locally.

## The local path

```bash
pip install -r requirements-analysis.txt
sudo apt install ffmpeg          # macOS: brew install ffmpeg

python scripts/fetch_reference.py "https://www.youtube.com/watch?v=..."
python scripts/analyze_video.py reference/<slug>/source.mp4
```

`--sample-fps` sets the shot-detection floor. The default of 4 resolves shots
down to about half a second; measured against a clip with known cuts, 2 fps
found 6 of 8 shots while 4 fps found all 8. Raise it for faster edits:

```bash
python scripts/analyze_video.py reference/<slug>/source.mp4 --sample-fps 6
```

## What comes out

```
reference/<slug>/
├── metadata.json      title, duration, native resolution, tags, chapters
├── transcript.txt     captions, deduplicated into plain text
├── analysis.json      the machine-readable style spec
├── REPORT.md          the same, human-readable
├── contact_sheet.jpg  one frame per detected shot, in a grid
└── frames/            those frames individually, named by timestamp
```

`analysis.json` measures:

- **Format** — resolution, aspect, orientation, fps, duration
- **Pacing** — shot count, cuts per minute, and the median shot length, which is
  the single most useful number: it sets how long each generated slide should
  hold
- **Motion** — static, moderate, or high-motion, from mean inter-frame delta
- **Palette** — dominant colours with their share of frame
- **Text layout** — which third of the frame carries the high-contrast detail

## What it cannot measure

Be aware of the limits before trusting a number:

- **Fonts.** Typeface identification from pixels is not attempted. Name the font
  yourself, or supply a `.ttf` in `assets/fonts/`.
- **Audio.** No loudness curve, no music/speech separation, no speaker
  diarisation. The transcript comes from captions, not from transcription — if
  the source has no captions, there is no transcript.
- **Gradual transitions.** Cut detection is tuned for hard cuts. A slow
  crossfade may register as one shot, or as several.
- **Meaning.** It reports that the bottom third is busy; it does not know that
  the busy thing is a subtitle bar.

## A note on sources

Analysing a video you own is unambiguous. Analysing someone else's to study its
structure is ordinary creative practice — but downloading it may sit awkwardly
with the host platform's terms, and the output of this pipeline should be your
own content in a similar *format*, not a re-cut of theirs. Measure the pacing;
write your own script.
