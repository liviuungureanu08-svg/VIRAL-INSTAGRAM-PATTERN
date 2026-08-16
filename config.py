"""Central configuration.

Every value is overridable by environment variable, so the same code runs
locally and in CI without edits. Nothing secret lives here — secrets come from
the environment only (see .env.example).
"""

import os
from pathlib import Path

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).parent
ASSETS_DIR = ROOT / "assets"
FONT_DIR = ASSETS_DIR / "fonts"
MUSIC_FILE = ASSETS_DIR / "music" / "bg_music.mp3"
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", ROOT / "output"))
CONTENT_PLAN_FILE = Path(os.getenv("CONTENT_PLAN_FILE", ROOT / "content_plan.json"))

CLIENT_SECRETS_FILE = Path(os.getenv("CLIENT_SECRETS_FILE", ROOT / "client_secrets.json"))
CREDENTIALS_FILE = Path(os.getenv("CREDENTIALS_FILE", ROOT / "credentials.json"))

# --- Series identity -------------------------------------------------------
SERIES_NAME = os.getenv("SERIES_NAME", "Build With AI")
AUTHOR_NAME = os.getenv("AUTHOR_NAME", "the team")
SERIES_TOPIC = os.getenv(
    "SERIES_TOPIC",
    "practical AI engineering for working developers",
)
SERIES_AUDIENCE = os.getenv(
    "SERIES_AUDIENCE",
    "a developer who can code but has no machine-learning background",
)

# --- Generation ------------------------------------------------------------
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LESSONS_PER_RUN = int(os.getenv("LESSONS_PER_RUN", "1"))
LESSONS_PER_PLAN = int(os.getenv("LESSONS_PER_PLAN", "20"))
SLIDES_PER_LESSON = int(os.getenv("SLIDES_PER_LESSON", "8"))

# --- Video -----------------------------------------------------------------
LONG_RESOLUTION = (1920, 1080)
SHORT_RESOLUTION = (1080, 1920)
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "24"))
SLIDE_PADDING_SECONDS = float(os.getenv("SLIDE_PADDING_SECONDS", "0.5"))
FADE_SECONDS = float(os.getenv("FADE_SECONDS", "0.4"))
MUSIC_VOLUME = float(os.getenv("MUSIC_VOLUME", "0.05"))
NARRATION_VOLUME = float(os.getenv("NARRATION_VOLUME", "1.2"))

# --- Publishing ------------------------------------------------------------
# Defaults to 'unlisted' on purpose. This pipeline publishes without a human in
# the loop; an unattended bot should not be able to push a broken or wrong video
# to a public channel. Flip to 'public' only once you trust your own output.
PRIVACY_STATUS = os.getenv("PRIVACY_STATUS", "unlisted")
YOUTUBE_CATEGORY_ID = os.getenv("YOUTUBE_CATEGORY_ID", "28")  # 28 = Science & Tech
UPLOAD_GAP_SECONDS = int(os.getenv("UPLOAD_GAP_SECONDS", "30"))
DRY_RUN = os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"}

# --- External APIs ---------------------------------------------------------
GOOGLE_API_KEY_VAR = "GOOGLE_API_KEY"
PEXELS_API_KEY_VAR = "PEXELS_API_KEY"
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "20"))

# --- Text-to-speech throttling --------------------------------------------
# Google's public TTS endpoint rate-limits bursts from shared CI IPs, and answers
# 200 OK with a truncated body rather than an error. Space requests out and
# verify the payload rather than trusting the status code.
TTS_LANG = os.getenv("TTS_LANG", "en")
TTS_TLD = os.getenv("TTS_TLD", "com")
TTS_MAX_ATTEMPTS = int(os.getenv("TTS_MAX_ATTEMPTS", "5"))
TTS_BACKOFF_SECONDS = float(os.getenv("TTS_BACKOFF_SECONDS", "5"))
TTS_MIN_GAP_SECONDS = float(os.getenv("TTS_MIN_GAP_SECONDS", "2"))
TTS_MIN_BYTES = int(os.getenv("TTS_MIN_BYTES", "1024"))

# --- Theme -----------------------------------------------------------------
COLOR_BACKDROP = (12, 17, 29)
COLOR_PANEL = (25, 40, 65)
COLOR_TITLE = (255, 255, 255)
COLOR_BODY = (232, 232, 236)
COLOR_MUTED = (176, 182, 194)
OVERLAY_DARKEN = int(os.getenv("OVERLAY_DARKEN", "150"))  # 0-255
BACKDROP_BLUR = float(os.getenv("BACKDROP_BLUR", "5"))
