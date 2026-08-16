"""YouTube Data API v3 publishing.

Authentication works in two modes:

* **Locally** — runs the interactive OAuth consent flow once and caches the
  result to `credentials.json`.
* **In CI** — refreshes the cached credentials silently. The interactive flow is
  refused outright when no TTY is available, because `run_local_server()` would
  otherwise block a scheduled job until it times out.
"""

from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

import config

YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
MAX_UPLOAD_ATTEMPTS = 5

# YouTube's own field limits. Exceeding either is a hard 400.
MAX_TITLE_CHARS = 100
MAX_DESCRIPTION_CHARS = 5000


class UploadError(RuntimeError):
    """Raised when a video could not be published."""


def _is_interactive() -> bool:
    if os.getenv("CI", "").lower() in {"1", "true"}:
        return False
    if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
        return False
    return sys.stdin.isatty()


def get_authenticated_service():
    """Return an authenticated YouTube API client."""
    credentials: Credentials | None = None

    if config.CREDENTIALS_FILE.exists():
        credentials = Credentials.from_authorized_user_file(
            str(config.CREDENTIALS_FILE), YOUTUBE_UPLOAD_SCOPE
        )

    if credentials and credentials.valid:
        return build("youtube", "v3", credentials=credentials)

    if credentials and credentials.expired and credentials.refresh_token:
        print("🔄 Refreshing expired credentials...")
        try:
            credentials.refresh(Request())
        except Exception as exc:
            raise UploadError(
                f"Could not refresh stored credentials ({exc}). The refresh token has "
                "likely been revoked or expired — re-run the local auth flow and "
                "update your CREDENTIALS_B64 secret."
            ) from exc
    else:
        if not _is_interactive():
            raise UploadError(
                "No valid credentials and no interactive terminal. In CI, provide a "
                "pre-authorised credentials.json via the CREDENTIALS_B64 secret — the "
                "browser consent flow cannot run here."
            )
        if not config.CLIENT_SECRETS_FILE.exists():
            raise UploadError(
                f"{config.CLIENT_SECRETS_FILE} not found. Download the OAuth client "
                "secret from the Google Cloud Console first."
            )
        print("🔐 Starting interactive OAuth consent flow...")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.CLIENT_SECRETS_FILE), scopes=YOUTUBE_UPLOAD_SCOPE
        )
        credentials = flow.run_local_server(port=0)

    config.CREDENTIALS_FILE.write_text(credentials.to_json(), encoding="utf-8")
    print(f"💾 Credentials cached to {config.CREDENTIALS_FILE.name}")
    return build("youtube", "v3", credentials=credentials)


def _resumable_upload(request) -> str:
    """Drive a resumable upload to completion, retrying transient failures."""
    response = None
    attempt = 0

    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"   ...{int(status.progress() * 100)}%")
        except HttpError as exc:
            if exc.resp.status not in RETRIABLE_STATUS_CODES:
                raise
            attempt += 1
            if attempt >= MAX_UPLOAD_ATTEMPTS:
                raise UploadError(
                    f"Upload failed after {MAX_UPLOAD_ATTEMPTS} retries: {exc}"
                ) from exc
            delay = (2**attempt) + random.uniform(0, 1)
            print(f"⚠️ Transient {exc.resp.status} from YouTube. Retrying in {delay:.1f}s...")
            time.sleep(delay)

    video_id = response.get("id")
    if not video_id:
        raise UploadError(f"YouTube accepted the upload but returned no video ID: {response}")
    return video_id


def upload_to_youtube(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str] | str,
    thumbnail_path: Path | None = None,
) -> str:
    """Publish a video and optional thumbnail. Returns the new video ID."""
    video_path = Path(video_path)
    if not video_path.exists():
        raise UploadError(f"Video file not found: {video_path}")

    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    title = (title or "Untitled").strip()[:MAX_TITLE_CHARS]
    description = (description or "").strip()[:MAX_DESCRIPTION_CHARS]

    if config.DRY_RUN:
        print(f"🧪 DRY_RUN — would upload {video_path.name} as {title!r} ({config.PRIVACY_STATUS})")
        return f"dry-run-{video_path.stem}"

    print(f"⬆️ Uploading {video_path.name} ({config.PRIVACY_STATUS})...")
    youtube = get_authenticated_service()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": config.YOUTUBE_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": config.PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    video_id = _resumable_upload(request)
    print(f"✅ Published: https://www.youtube.com/watch?v={video_id}")

    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path)),
            ).execute()
            print("✅ Thumbnail set.")
        except HttpError as exc:
            # Custom thumbnails need a verified channel; never fail the run for it.
            print(f"⚠️ Could not set thumbnail (channel may not be verified): {exc}")

    return video_id
