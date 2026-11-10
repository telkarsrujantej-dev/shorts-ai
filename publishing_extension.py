
# publishing_extension.py
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import main as core

router = APIRouter(prefix="/publish", tags=["YouTube Publishing"])
log = logging.getLogger(__name__)
lock = Lock()

TOKEN = core.BASE_DIR / "secrets" / "youtube_token.json"
HISTORY = core.BASE_DIR / "youtube_upload_history.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def read_history():
    try:
        data = json.loads(HISTORY.read_text(encoding="utf-8"))
        return data.get("items", [])
    except (OSError, ValueError, AttributeError):
        return []


def save_history(items):
    core.save_data(HISTORY, {"items": items})


def get_service():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        raise HTTPException(
            503, "Install Google API Python dependencies."
        ) from None

    if not TOKEN.is_file():
        raise HTTPException(
            401, "YouTube not connected. Run connect_youtube.py."
        )

    try:
        saved = json.loads(TOKEN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(
            401, "Invalid YouTube token. Reconnect the channel."
        ) from None

    if not set(SCOPES).issubset(set(saved.get("scopes") or [])):
        raise HTTPException(
            401,
            "Reauthorize YouTube with upload and readonly permissions."
        )

    try:
        credentials = Credentials.from_authorized_user_file(
            str(TOKEN), scopes=SCOPES
        )

        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            TOKEN.write_text(credentials.to_json(), encoding="utf-8")

        if not credentials.valid:
            raise HTTPException(
                401, "YouTube token expired. Reconnect your channel."
            )

        return build(
            "youtube", "v3",
            credentials=credentials,
            cache_discovery=False
        )

    except HTTPException:
        raise
    except Exception:
        log.exception("YouTube authentication error")
        raise HTTPException(
            401, "YouTube authorization failed. Reconnect your channel."
        ) from None


def authorized_channel(service):
    try:
        response = service.channels().list(
            part="snippet",
            mine=True,
        ).execute()

        channels = response.get("items") or []

        if not channels:
            raise HTTPException(
                404,
                "No YouTube channel found for this Google account. "
                "Choose the account that owns your channel."
            )

        channel = channels[0]

        return {
            "channel_id": channel["id"],
            "channel_name": channel["snippet"]["title"],
        }

    except HTTPException:
        raise
    except Exception:
        log.exception("YouTube channel lookup failed")
        raise HTTPException(
            403,
            "Unable to read your YouTube channel. "
            "Check the API, OAuth scopes, and connected account."
        ) from None


@router.get("/channel")
def channel_status():
    try:
        service = get_service()
        channel = authorized_channel(service)

        return {"connected": True, **channel}

    except HTTPException as error:
        return {
            "connected": False,
            "reason": error.detail,
        }


@router.get("/history")
def upload_history():
    return {"items": read_history()}


def sha256_file(path):
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


class PublishShort(BaseModel):
    filename: str
    channel_id: str
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    made_for_kids: bool


@router.post("/upload-one")
def upload_one(body: PublishShort):
    from googleapiclient.http import MediaFileUpload

    if not core.CLIP_PATTERN.fullmatch(body.filename):
        raise HTTPException(400, "Invalid Short filename.")

    path = core.CLIPS / body.filename

    if not path.is_file():
        raise HTTPException(404, "Generated Short not found.")

    service = get_service()
    channel = authorized_channel(service)

    # Never publish to a different channel silently.
    if body.channel_id != channel["channel_id"]:
        raise HTTPException(
            409,
            "Connected YouTube channel changed. Review the channel again."
        )

    fingerprint = sha256_file(path)

    with lock:
        for entry in read_history():
            if (
                entry.get("sha256") == fingerprint
                and entry.get("channel_id") == body.channel_id
            ):
                return {
                    "uploaded": True,
                    "already_uploaded": True,
                    "youtube_url": entry["youtube_url"],
                }

    try:
        request = service.videos().insert(
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
            media_body=MediaFileUpload(
                str(path),
                mimetype="video/mp4",
                chunksize=8 * 1024 * 1024,
                resumable=True,
            ),
        )

        result = None

        while result is None:
            _, result = request.next_chunk(num_retries=3)

        video_id = result.get("id")

        if not video_id:
            raise HTTPException(
                502, "YouTube returned no video ID."
            )

    except HTTPException:
        raise
    except Exception as error:
        log.exception("YouTube video upload failed")

        status = getattr(
            getattr(error, "resp", None), "status", None
        )

        if status in (401, 403):
            detail = (
                "YouTube denied the upload. Check OAuth access, "
                "channel permissions, and API quota."
            )
        elif status == 400:
            detail = "YouTube rejected the video or its metadata."
        else:
            detail = (
                "Upload failed or its result is uncertain. "
                "Check YouTube Studio before retrying."
            )

        raise HTTPException(502, detail) from None

    record = {
        "filename": body.filename,
        "sha256": fingerprint,
        "channel_id": body.channel_id,
        "title": body.title,
        "youtube_url": (
            "https://www.youtube.com/watch?v=" + video_id
        ),
        "privacy": "private",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    with lock:
        items = read_history()
        items.insert(0, record)
        save_history(items)

    return {
        "uploaded": True,
        "already_uploaded": False,
        "youtube_url": record["youtube_url"],
    }
