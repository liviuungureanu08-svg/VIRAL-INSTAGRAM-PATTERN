# Autonomous Course Generator

An end-to-end pipeline that writes, narrates, renders, and publishes an
educational video series to YouTube on a daily schedule — with no human in the
loop.

One run takes the next pending lesson from `content_plan.json`, scripts it with
Gemini, narrates each slide, renders the frames, assembles a long-form video and
a vertical short, uploads both, and commits the advanced plan back to the repo.

```
content_plan.json ──▶ Gemini ──▶ narration (gTTS) ──▶ slides (Pillow)
                                                            │
                        YouTube ◀── MP4 ◀── assembly (MoviePy/ffmpeg)
                           │
                           └──▶ content_plan.json updated + committed
```

---

## How it works

| Stage | Module | What happens |
|---|---|---|
| 1. Plan | `src/curriculum.py` | Loads the plan; generates a new 20-lesson curriculum when it is missing or exhausted |
| 2. Script | `src/curriculum.py` | Gemini writes 8 slides, a short-form highlight, and hashtags |
| 3. Narrate | `src/speech.py` | Per-slide TTS, normalised to PCM WAV for exact durations |
| 4. Render | `src/visuals.py` | Pillow composes slides and thumbnails over a Pexels backdrop |
| 5. Assemble | `src/video.py` | Each slide is held for the length of its own narration, music mixed under |
| 6. Publish | `src/uploader.py` | Resumable upload of both cuts, plus thumbnails |
| 7. Advance | `main.py` | Marks the lesson complete and records its video ID |

Two cuts come out of every run: a 1920×1080 lesson and a 1080×1920 short whose
description links back to the full video.

---

## Quick start

```bash
git clone https://github.com/liviuungureanu08-svg/viral-instagram-pattern.git
cd viral-instagram-pattern

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# ffmpeg is required
sudo apt install ffmpeg        # macOS: brew install ffmpeg

cp .env.example .env           # then fill in GOOGLE_API_KEY
```

Do a dry run first — it builds both videos and uploads nothing:

```bash
export GOOGLE_API_KEY=...
DRY_RUN=1 python main.py
```

The MP4s land in `output/`. Watch them before you let anything publish.

---

## Connecting YouTube

1. In the [Google Cloud Console](https://console.cloud.google.com/), enable the
   **YouTube Data API v3**.
2. Create an **OAuth client ID** of type *Desktop app*, download it, and save it
   as `client_secrets.json` in the project root.
3. Run `python main.py` once locally. A browser opens for consent, and
   `credentials.json` is written on success.
4. Base64-encode both files for CI:

   ```bash
   base64 -w0 client_secrets.json   # -w0 is GNU; on macOS use: base64 -i client_secrets.json
   base64 -w0 credentials.json
   ```

5. Add them as repository secrets (below).

> Both JSON files are gitignored. They grant upload access to your channel —
> if either is ever committed, **rotate it immediately**. Deleting the file does
> not remove it from git history.

---

## Configuration

### Secrets — *Settings → Secrets and variables → Actions → Secrets*

| Secret | Required | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | ✅ | Gemini API key ([AI Studio](https://aistudio.google.com/apikey)) |
| `CREDENTIALS_B64` | ✅ | Base64 of `credentials.json` |
| `CLIENT_SECRET_B64` | ✅ | Base64 of `client_secrets.json` |
| `PEXELS_API_KEY` | ➖ | Slide backdrops; falls back to flat colour |

### Variables — *…→ Variables*

| Variable | Default | Purpose |
|---|---|---|
| `PRIVACY_STATUS` | `unlisted` | `unlisted`, `private`, or `public` |
| `SERIES_NAME` | `Build With AI` | Shown in slide footers and descriptions |
| `SERIES_TOPIC` | — | Subject matter passed to the model |

Everything in `config.py` is environment-overridable — series identity, slide
count, resolution, fade lengths, volumes, TTS retry policy.

**`PRIVACY_STATUS` defaults to `unlisted` on purpose.** Nothing reviews these
videos before they go out. Leave it unlisted until you have watched enough runs
to trust the output.

---

## Running it

The workflow runs daily at 07:00 UTC, or on demand from the **Actions** tab with
`dry_run` and `limit` inputs.

```bash
python main.py                  # next pending lesson
python main.py --limit 3        # next three
DRY_RUN=1 python main.py        # build, don't upload
python scripts/preflight.py     # safety checks only
```

`scripts/preflight.py` runs before every CI job and fails the build if a
credential file has been committed, or if `GOOGLE_API_KEY` is missing.

---

## Assets

Two asset slots are intentionally left empty, because filling them from a public
repo would mean redistributing content that isn't licensed for it:

- **Font** — `assets/fonts/`. The renderer resolves a system font (DejaVu on
  CI, Arial on macOS/Windows) and falls back to Pillow's built-in. Drop a
  `custom.ttf` in that folder to override.
- **Music** — `assets/music/bg_music.mp3`. Absent by default; supply your own
  licensed track and it is mixed in automatically.

---

## Costs and quotas

- **YouTube Data API** — 10,000 units/day; each upload costs ~1,600, so roughly
  **6 uploads/day**. One run publishes two.
- **Gemini** — two calls per run on `gemini-2.5-flash`.
- **gTTS** — unofficial endpoint with no SLA. It throttles bursts from shared CI
  IPs and signals it with a truncated `200 OK`, so `src/speech.py` validates the
  payload by size and retries with backoff.
- **GitHub Actions** — a run takes roughly 10–25 minutes depending on lesson
  length.

---

## Attribution

The architecture of this pipeline follows the approach demonstrated in
[ChaitanyaEswarRajeshJakki/gemini-youtube-automation](https://github.com/ChaitanyaEswarRajeshJakki/gemini-youtube-automation).
This is an independent implementation of that idea, not a fork — no code was
copied, and it differs deliberately in several places:

| | Upstream | Here |
|---|---|---|
| Publish default | `public` | `unlisted` |
| Rendering | Pillow + ImageMagick (`policy.xml` patched in CI) | Pillow only |
| Audio conversion | `pydub` | `ffmpeg` directly |
| MoviePy | `1.0.3` (2020) | `2.1+` |
| Pillow | `9.5.0` (known CVEs) | `>=10.4` |
| Model output | Parsed directly | Validated and sanitised before use |
| Remote images | Decoded as received | Size-capped, bomb-guarded |
| CI auth | Interactive flow can hang a job | Refused without a TTY |
| Secret hygiene | — | `scripts/preflight.py`; credentials wiped after the run |
| Structure | One 406-line module | Five focused modules |

## License

MIT — see [LICENSE](LICENSE).
