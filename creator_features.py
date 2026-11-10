
# creator_features.py

import json
import logging
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import main as core

router = APIRouter(prefix="/creator", tags=["Creator features"])
log = logging.getLogger(__name__)

DOWNLOAD_HISTORY = core.BASE_DIR / "download_history.json"
AUDIO_FOLDER = core.BASE_DIR / "audio_exports"
SECRETS_FOLDER = core.BASE_DIR / "secrets"

AUDIO_FOLDER.mkdir(exist_ok=True)
SECRETS_FOLDER.mkdir(exist_ok=True)

YOUTUBE_CLIENT = core.BASE_DIR / "youtube_client_secret.json"
YOUTUBE_TOKEN = SECRETS_FOLDER / "youtube_token.json"

YOUTUBE_SCOPE = [
    "https://www.googleapis.com/auth/youtube.upload"
]

history_lock = threading.Lock()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def clip_path(filename: str) -> Path:
    if not core.CLIP_PATTERN.fullmatch(filename):
        raise HTTPException(400, "Invalid Short filename.")

    path = core.CLIPS / filename

    if not path.is_file():
        raise HTTPException(404, "Generated Short not found.")

    return path


def read_download_history():
    try:
        data = json.loads(
            DOWNLOAD_HISTORY.read_text(encoding="utf-8")
        )
        return data.get("items", [])
    except (OSError, ValueError, AttributeError):
        return []


def record_download(filename):
    with history_lock:
        items = read_download_history()

        items = [
            item for item in items
            if item.get("filename") != filename
        ]

        items.insert(0, {
            "filename": filename,
            "title": filename,
            "video_url": "/clips/" + filename,
            "downloaded_at": utc_now(),
        })

        core.save_data(
            DOWNLOAD_HISTORY,
            {"items": items[:300]},
        )


# 1. MP4 DOWNLOAD HISTORY
# Only this route adds an item to Downloads.

@router.get("/download/{filename}")
def download_mp4(filename: str):
    path = clip_path(filename)
    record_download(filename)

    return FileResponse(
        path,
        media_type="video/mp4",
        filename=filename,
    )


@router.get("/downloads")
def list_downloads():
    items = [
        item for item in read_download_history()
        if (
            core.CLIP_PATTERN.fullmatch(
                item.get("filename", "")
            )
            and (core.CLIPS / item["filename"]).is_file()
        )
    ]
    return {"items": items}


# 2. INDEPENDENT MP3 EXPORT

@router.get("/mp3/{filename}")
def export_mp3(filename: str):
    source = clip_path(filename)

    output = AUDIO_FOLDER / (
        Path(filename).stem + ".mp3"
    )

    if not shutil.which("ffmpeg"):
        raise HTTPException(
            503, "FFmpeg is not available."
        )

    if (
        not output.exists()
        or output.stat().st_mtime_ns
           < source.stat().st_mtime_ns
    ):
        temporary = output.with_name(
            output.stem + ".temporary.mp3"
        )

        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-y", "-i", str(source),
            "-map", "0:a:0",
            "-vn",
            "-codec:a", "libmp3lame",
            "-q:a", "2",
            str(temporary),
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )

            if result.returncode != 0:
                raise HTTPException(
                    422,
                    "The selected Short could not be "
                    "converted to MP3. Check its audio.",
                )

            temporary.replace(output)

        except subprocess.TimeoutExpired:
            raise HTTPException(
                504, "MP3 conversion timed out."
            ) from None

        finally:
            temporary.unlink(missing_ok=True)

    return FileResponse(
        output,
        media_type="audio/mpeg",
        filename=output.name,
    )


# 3. IMPROVED AI ANALYSIS
# Transcribe before calling Gemini when possible.

@router.post("/analyze/{filename}")
def analyze_with_transcript(
    filename: str,
    force: bool = False,
):
    core.validate_video(filename)

    transcript_available = False
    warning = None

    try:
        transcript = core.get_full_transcript(filename)
        transcript_available = bool(
            transcript.get("segments")
        )

    except Exception:
        log.exception(
            "Full transcription failed before AI analysis"
        )
        warning = (
            "Transcript unavailable. "
            "Gemini will analyze the video directly."
        )

    result = core.highlights(
        filename,
        force=force,
    )

    return {
        **result,
        "transcript_used": transcript_available,
        "warning": warning,
    }


# 4. YOUTUBE DATA API

def youtube_credentials():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

    except ImportError:
        raise HTTPException(
            503,
            "Install the Google API dependencies.",
        ) from None

    if not YOUTUBE_TOKEN.is_file():
        raise HTTPException(
            401,
            "Connect a YouTube account first.",
        )

    try:
        credentials = Credentials.from_authorized_user_file(
            str(YOUTUBE_TOKEN),
            scopes=YOUTUBE_SCOPE,
        )

        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())

            YOUTUBE_TOKEN.write_text(
                credentials.to_json(),
                encoding="utf-8",
            )

        if not credentials.valid:
            raise HTTPException(
                401,
                "YouTube authorization expired. "
                "Reconnect your account.",
            )

        return credentials

    except HTTPException:
        raise
    except Exception:
        log.exception("YouTube OAuth authorization failed")
        raise HTTPException(
            401,
            "YouTube authorization failed. "
            "Reconnect your account.",
        ) from None


@router.get("/youtube/status")
def youtube_status():
    try:
        youtube_credentials()
        return {"connected": True}
    except HTTPException:
        return {"connected": False}


class YouTubeUpload(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    made_for_kids: bool


@router.post("/youtube/upload/{filename}")
def upload_short_to_youtube(
    filename: str,
    body: YouTubeUpload,
):
    source = clip_path(filename)
    credentials = youtube_credentials()

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from googleapiclient.errors import HttpError

    except ImportError:
        raise HTTPException(
            503,
            "Google API Python client is not installed.",
        ) from None

    try:
        youtube = build(
            "youtube",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )

        media = MediaFileUpload(
            str(source),
            mimetype="video/mp4",
            chunksize=8 * 1024 * 1024,
            resumable=True,
        )

        operation = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": body.title.strip(),
                    "description": body.description,
                    "categoryId": "22",
                },
                "status": {
                    "privacyStatus": "private",
                    "selfDeclaredMadeForKids": body.made_for_kids,
                },
            },
            media_body=media,
        )

        result = None

        while result is None:
            _, result = operation.next_chunk(
                num_retries=3
            )

        video_id = result.get("id")

        if not video_id:
            raise HTTPException(
                502,
                "YouTube did not return a video ID.",
            )

        return {
            "uploaded": True,
            "video_id": video_id,
            "youtube_url": (
                "https://www.youtube.com/watch?v="
                + video_id
            ),
            "privacy": "private",
        }

    except HTTPException:
        raise
    except HttpError as error:
        log.exception("YouTube API rejected the upload")
        raise HTTPException(
            502,
            f"YouTube upload failed "
            f"(HTTP {error.resp.status}).",
        ) from None
    except Exception:
        log.exception("YouTube upload failed")
        raise HTTPException(
            502,
            "YouTube upload failed. Check server logs.",
        ) from None
