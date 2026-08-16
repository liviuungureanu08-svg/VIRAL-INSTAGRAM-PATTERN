"""Video assembly with MoviePy 2.x.

Each slide is held for exactly the length of its own narration, so audio and
visuals stay in sync no matter how long the model's text turns out to be.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    ImageClip,
    afx,
    concatenate_videoclips,
    vfx,
)

import config


class VideoError(RuntimeError):
    """Raised when a video could not be assembled."""


def _background_music(duration: float) -> AudioFileClip | None:
    """Return a looped, ducked music bed, or None when no track is supplied.

    No music is vendored in this repo — drop your own licensed track at
    assets/music/bg_music.mp3 and it is picked up automatically.
    """
    if not config.MUSIC_FILE.exists():
        return None

    try:
        music = AudioFileClip(str(config.MUSIC_FILE))
        if music.duration < duration:
            music = music.with_effects([afx.AudioLoop(duration=duration)])
        else:
            music = music.subclipped(0, duration)
        return music.with_effects([afx.MultiplyVolume(config.MUSIC_VOLUME)])
    except Exception as exc:  # noqa: BLE001 - music is optional, never fatal
        print(f"⚠️ Could not load background music: {exc}")
        return None


def create_video(
    slide_paths: list[Path],
    audio_paths: list[Path],
    output_path: Path,
    video_type: str,
) -> Path:
    """Assemble slides + per-slide narration into a finished MP4."""
    if not slide_paths or not audio_paths:
        raise VideoError("No slides or narration supplied.")
    if len(slide_paths) != len(audio_paths):
        raise VideoError(
            f"Slide/narration mismatch: {len(slide_paths)} slides, {len(audio_paths)} audio clips."
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"🎬 Assembling {video_type} video ({len(slide_paths)} slides)...")

    opened: list = []
    try:
        clips = []
        for image_path, audio_path in zip(slide_paths, audio_paths):
            narration = AudioFileClip(str(audio_path))
            opened.append(narration)
            duration = narration.duration + config.SLIDE_PADDING_SECONDS

            clip = (
                ImageClip(str(image_path))
                .with_duration(duration)
                .with_audio(narration)
                .with_effects(
                    [vfx.FadeIn(config.FADE_SECONDS), vfx.FadeOut(config.FADE_SECONDS)]
                )
            )
            clips.append(clip)
            opened.append(clip)

        video = concatenate_videoclips(clips, method="compose")
        opened.append(video)

        music = _background_music(video.duration)
        if music is not None and video.audio is not None:
            opened.append(music)
            narration_bed = video.audio.with_effects(
                [afx.MultiplyVolume(config.NARRATION_VOLUME)]
            )
            video = video.with_audio(CompositeAudioClip([narration_bed, music]))
            opened.append(video)
            print("🎵 Background music mixed in.")

        video.write_videofile(
            str(output_path),
            fps=config.VIDEO_FPS,
            codec="libx264",
            audio_codec="aac",
            audio_bitrate="192k",
            preset="medium",
            threads=4,
            logger=None,
        )
        print(f"✅ {video_type.capitalize()} video written: {output_path}")
        return output_path

    except Exception as exc:
        raise VideoError(f"Failed to assemble {video_type} video: {exc}") from exc
    finally:
        for clip in opened:
            with suppress(Exception):
                clip.close()
