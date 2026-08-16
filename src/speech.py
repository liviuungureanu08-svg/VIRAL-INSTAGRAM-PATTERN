"""Text-to-speech narration via gTTS, normalised to WAV.

Two problems this module exists to solve:

1. Google's public TTS endpoint throttles bursts from shared CI IP ranges and
   signals it by returning 200 OK with a truncated body — so the response is
   validated by size, not by status code.
2. Variable-bitrate MP3 durations are unreliable when moviepy seeks them, which
   desynchronises narration from slides. Everything is converted to PCM WAV so
   each clip reports an exact duration.
"""

from __future__ import annotations

import random
import shutil
import subprocess
import time
from pathlib import Path

from gtts import gTTS

import config


class SpeechError(RuntimeError):
    """Raised when narration could not be produced."""


_last_request_at = 0.0


def _throttle() -> None:
    """Space consecutive TTS requests to stay under the rate limiter."""
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < config.TTS_MIN_GAP_SECONDS:
        time.sleep(config.TTS_MIN_GAP_SECONDS - elapsed)
    _last_request_at = time.monotonic()


def _require_ffmpeg() -> str:
    """Locate an ffmpeg binary.

    Prefers a system install, but falls back to the one imageio-ffmpeg vendors
    for MoviePy — so the pipeline runs on a machine with no system ffmpeg.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - fall through to a clear error
        pass

    raise SpeechError(
        "No ffmpeg binary found. Install it (apt install ffmpeg / brew install "
        "ffmpeg), or ensure imageio-ffmpeg is present."
    )


def _to_wav(mp3_path: Path, wav_path: Path) -> None:
    """Transcode MP3 to 16-bit PCM WAV.

    Invoked with an argument list and no shell, so nothing in the path is
    interpreted as a command.
    """
    result = subprocess.run(
        [
            _require_ffmpeg(),
            "-y",
            "-loglevel", "error",
            "-i", str(mp3_path),
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SpeechError(f"ffmpeg failed to convert narration: {result.stderr.strip()}")


def text_to_speech(text: str, output_path: Path) -> Path:
    """Render `text` to a WAV file next to `output_path`, returning its path."""
    text = (text or "").strip()
    if not text:
        raise SpeechError("Refusing to synthesise empty narration.")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_mp3 = output_path.with_name(output_path.stem + "_temp.mp3")
    wav_path = output_path.with_suffix(".wav")

    last_error: Exception | None = None
    for attempt in range(1, config.TTS_MAX_ATTEMPTS + 1):
        try:
            _throttle()
            gTTS(text=text, lang=config.TTS_LANG, tld=config.TTS_TLD, slow=False).save(str(temp_mp3))

            # A throttled response still writes a file — just a stub one.
            if temp_mp3.stat().st_size < config.TTS_MIN_BYTES:
                raise SpeechError("TTS returned an empty or truncated audio stream.")

            _to_wav(temp_mp3, wav_path)
            temp_mp3.unlink(missing_ok=True)
            print(f"🎤 Narration ready: {wav_path.name}")
            return wav_path

        except Exception as exc:  # noqa: BLE001 - retried and re-raised below
            last_error = exc
            temp_mp3.unlink(missing_ok=True)

            if attempt == config.TTS_MAX_ATTEMPTS:
                break

            delay = config.TTS_BACKOFF_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 2)
            print(
                f"⚠️ TTS attempt {attempt}/{config.TTS_MAX_ATTEMPTS} failed ({exc}). "
                f"Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)

    raise SpeechError(
        f"Narration failed after {config.TTS_MAX_ATTEMPTS} attempts: {last_error}"
    )
