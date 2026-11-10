
# workflow_extension.py
"""Additional routes for the approved Shorts AI workflow."""

import hashlib
import json
import logging
import math
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import main as core

router = APIRouter(prefix="/workflow", tags=["Creator workflow"])
log = logging.getLogger(__name__)
lock = threading.Lock()

MANUAL = core.BASE_DIR / "manual_selections"
REVIEWS = core.BASE_DIR / "manual_subtitle_reviews"
GALLERY = core.BASE_DIR / "my_highlights.json"

MANUAL.mkdir(exist_ok=True)
REVIEWS.mkdir(exist_ok=True)


class UrlInput(BaseModel):
    url: str


class SelectedClip(BaseModel):
    start: float
    end: float
    title: str = "Manual Short"


class SelectionBody(BaseModel):
    highlights: list[SelectedClip]


class RenderBody(BaseModel):
    selection_mode: str
    quality: str = "fast"


def selection_path(filename):
    return MANUAL / f"{Path(filename).stem}.json"


def review_path(filename, index):
    return REVIEWS / f"{Path(filename).stem}_{index}.json"



def get_manual(filename):
    core.validate_video(filename)

    path = selection_path(filename)

    if not path.is_file():
        return []

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return []

        if data.get("filename") != filename:
            return []

        if data.get("source_identity") != core.source_identity(filename):
            return []

        highlights = data.get("highlights", [])

        if not isinstance(highlights, list):
            return []

        return highlights

    except (OSError, ValueError, TypeError):
        return []


def validate_clips(filename, items):
    video_path = core.validate_video(filename)
    duration = core.get_video_duration(video_path)

    if not 1 <= len(items) <= 6:
        raise HTTPException(
            400, "Choose between 1 and 6 highlights."
        )

    clips = []

    for index, item in enumerate(items, 1):
        a = float(item.start)
        b = float(item.end)

        if not all(math.isfinite(x) for x in (a, b)):
            raise HTTPException(400, "Invalid timestamps.")

        if not 0 <= a < b <= duration:
            raise HTTPException(
                400, "Highlight is outside the video."
            )

        if b - a > 60:
            raise HTTPException(
                400, "Highlights cannot exceed 60 seconds."
            )

        a = round(a, 2)
        b = round(b, 2)

        if b <= a:
            raise HTTPException(400, "Highlight is too short.")

        clips.append({
            "start": a,
            "end": b,
            "title": item.title.strip() or f"Short {index}",
            "reason": "Manually selected",
            "score": 10,
        })

    clips.sort(key=lambda item: item["start"])

    for first, second in zip(clips, clips[1:]):
        if first["end"] > second["start"]:
            raise HTTPException(
                400, "Manual highlights cannot overlap."
            )

    return clips


@router.post("/manual/{filename}/selections")
def save_manual(filename: str, body: SelectionBody):
    selected = validate_clips(filename, body.highlights)

    core.save_data(selection_path(filename), {
        "filename": filename,
        "source_identity": core.source_identity(filename),
        "highlights": selected,
        "revision": uuid4().hex,
    })

    return {"highlights": selected}


@router.get("/manual/{filename}/selections")
def load_manual(filename: str):
    return {"highlights": get_manual(filename)}


def manual_doc(filename, index):
    highlights = get_manual(filename)

    if not 0 <= index < len(highlights):
        raise HTTPException(
            404, "Save the manual highlight first."
        )

    clip = highlights[index]
    a = clip["start"]
    b = clip["end"]

    transcript = core.get_selected_transcript(
        filename, highlights
    )

    path = review_path(filename, index)
    doc = core.load_cached(path, filename, "cues")

    if core.doc_matches(doc, a, b, transcript):
        return doc

    doc = core.build_subtitle_doc(
        filename, index, a, b, transcript
    )

    core.backup_file(path)
    core.save_data(path, doc)

    return doc


@router.get("/manual/{filename}/subtitles/{index}")
def get_manual_subtitles(filename: str, index: int):
    return manual_doc(filename, index)


@router.put("/manual/{filename}/subtitles/{index}")
def save_manual_subtitles(
    filename: str,
    index: int,
    body: core.SubtitleSaveBody,
):
    doc = manual_doc(filename, index)

    if body.revision != doc["revision"]:
        raise HTTPException(
            409, "Subtitles changed. Reopen the editor."
        )

    if len(body.cues) > 200:
        raise HTTPException(400, "Too many caption cues.")

    updated = []

    for i, cue in enumerate(body.cues):
        a = round(cue.start, 2)
        b = round(cue.end, 2)
        text = " ".join(cue.text.split())

        if (
            cue.id != i
            or not all(math.isfinite(t) for t in (a, b))
            or not 0 <= a < b <= doc["duration"]
        ):
            raise HTTPException(
                400, "Invalid caption timestamps or IDs."
            )

        if (
            not core.meaningful(text)
            or not core.latin_text(text)
            or len(text) > 500
        ):
            raise HTTPException(
                400, "Use readable English or Romanized Hindi."
            )

        if updated and a < updated[-1]["end"]:
            raise HTTPException(
                400, "Caption intervals cannot overlap."
            )

        updated.append({
            "id": i,
            "start": a,
            "end": b,
            "text": text,
        })

    path = review_path(filename, index)

    core.backup_file(path)

    doc.update(
        cues=updated,
        mode=body.mode,
        revision=uuid4().hex,
        manual_reviewed=True,
    )

    core.save_data(path, doc)

    return doc


def reviewed_manual_segments(filename, highlights, transcript):
    output = []

    for index, clip in enumerate(highlights):
        a = clip["start"]
        b = clip["end"]

        doc = core.load_cached(
            review_path(filename, index),
            filename,
            "cues",
        )

        reviewed = core.doc_matches(
            doc, a, b, transcript
        ) and (
            doc.get("manual_reviewed")
            or doc.get("ai_reviewed")
        )

        if reviewed:
            events = [
                (
                    a + cue["start"],
                    a + cue["end"],
                    cue["text"],
                )
                for cue in doc["cues"]
            ]
        else:
            if transcript.get("status") == "unavailable":
                raise HTTPException(
                    422,
                    "Transcription unavailable. "
                    "Edit and save the captions before exporting.",
                )

            events, _ = core.caption_events(
                transcript["segments"], a, b
            )

        for start, end, text in events:
            output.append({
                "start": start,
                "end": end,
                "text": text,
                "words": [],
                "caption_cue": True,
            })

    return sorted(output, key=lambda item: item["start"])


def render_manual(filename, quality):
    highlights = get_manual(filename)

    if not highlights:
        raise HTTPException(
            400, "Add manual highlights before exporting."
        )

    transcript = core.get_selected_transcript(
        filename, highlights
    )

    segments = reviewed_manual_segments(
        filename, highlights, transcript
    )

    # Unique source name prevents overwriting AI output.
    unique = f"{uuid4().hex}.mp4"
    temporary_source = core.UPLOADS / unique

    try:
        source = core.validate_video(filename)

        try:
            os.link(source, temporary_source)
        except OSError:
            shutil.copy2(source, temporary_source)

        clips = core.create_shorts(
            unique,
            highlights,
            segments,
            mode=quality,
        )

        for item, original in zip(clips, highlights):
            item["title"] = original["title"]

        return {
            "clips": clips,
            "warnings": transcript.get("warnings", []),
        }
    finally:
        temporary_source.unlink(missing_ok=True)


def gallery_items():
    try:
        data = json.loads(GALLERY.read_text(encoding="utf-8"))
        return data.get("items", [])
    except (OSError, ValueError, AttributeError):
        return []


def register_clips(clips, filename, mode):
    with lock:
        items = gallery_items()
        now = datetime.now(timezone.utc).isoformat()

        for clip in clips:
            name = clip.get("filename")
            if not name:
                continue

            # Only index clips served by our existing API.
            if not core.CLIP_PATTERN.fullmatch(name):
                continue

            items = [
                item for item in items
                if item["filename"] != name
            ]

            items.insert(0, {
                "id": uuid4().hex,
                "filename": name,
                "source_filename": filename,
                "title": clip.get("title") or "My Short",
                "video_url": "/clips/" + name,
                "selection_mode": mode,
                "created_at": now,
            })

        core.save_data(GALLERY, {
            "items": items[:200]
        })


@router.get("/gallery")
def gallery():
    return {"items": gallery_items()}


@router.post("/render/{filename}")
def render_workflow(filename: str, body: RenderBody):
    core.validate_video(filename)

    if body.quality not in ("fast", "quality"):
        raise HTTPException(400, "Invalid render quality.")

    if body.selection_mode not in ("ai", "manual"):
        raise HTTPException(400, "Invalid selection mode.")

    try:
        if body.selection_mode == "manual":
            result = render_manual(filename, body.quality)
        else:
            result = core.render_video(
                filename,
                mode=body.quality,
                language="auto",
            )

        register_clips(
            result.get("clips", []),
            filename,
            body.selection_mode,
        )

        return result

    except HTTPException:
        raise
    except Exception:
        log.exception("Video render failed")
        raise HTTPException(
            500, "Rendering failed. Check the server terminal."
        ) from None


# Optional URL support, restricted to supported video hosts.
# Requires: pip install yt-dlp
SUPPORTED_HOSTS = (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "tiktok.com",
    "instagram.com",
)


@router.post("/ingest-url")
def ingest_video_url(body: UrlInput):
    parsed = urlparse(body.url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")

    allowed = any(
        host == domain or host.endswith("." + domain)
        for domain in SUPPORTED_HOSTS
    )

    if parsed.scheme != "https" or not allowed:
        raise HTTPException(
            400,
            "Enter a public HTTPS YouTube, Vimeo, "
            "TikTok or Instagram video URL.",
        )

    try:
        import yt_dlp
    except ImportError:
        raise HTTPException(
            501, "Install yt-dlp to enable video URLs."
        ) from None

    max_bytes = 200 * 1024 * 1024

    with tempfile.TemporaryDirectory(
        prefix="url_input_", dir=core.UPLOADS
    ) as temporary:
        folder = Path(temporary)

        def progress(data):
            if data.get("downloaded_bytes", 0) > max_bytes:
                raise RuntimeError("Video exceeds 200 MB.")

        options = {
            "outtmpl": str(folder / "source.%(ext)s"),
            "format": (
                "bv*[height<=720]+ba/"
                "b[ext=mp4]/best"
            ),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "max_filesize": max_bytes,
            "progress_hooks": [progress],
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([body.url])

            candidates = list(folder.glob("*.mp4"))

            if not candidates:
                raise RuntimeError("No MP4 output")

            source = candidates[0]

            if source.stat().st_size > max_bytes:
                raise RuntimeError("Video exceeds 200 MB.")

            digest = hashlib.sha256()

            with source.open("rb") as stream:
                for chunk in iter(
                    lambda: stream.read(1024 * 1024), b""
                ):
                    digest.update(chunk)

            filename = digest.hexdigest()[:32] + ".mp4"
            destination = core.UPLOADS / filename

            if not destination.exists():
                shutil.move(str(source), str(destination))

            return {
                "filename": filename,
                "message": "Video imported successfully.",
            }

        except HTTPException:
            raise
        except Exception:
            log.exception("Video URL import failed")
            raise HTTPException(
                422,
                "Could not import the video. "
                "Check its URL, access permissions and size.",
            ) from None
