
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path

import json
import math
import re

from gemini_analyzer import get_video_duration


router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent

UPLOAD_DIR = BASE_DIR / "uploads"
HIGHLIGHTS_DIR = BASE_DIR / "highlights"

SAFE_FILENAME = re.compile(
    r"[0-9a-f]{32}\.(mp4|mov|mkv|webm)"
)


class ClipTiming(BaseModel):
    start: float
    end: float


@router.post("/update-highlight/{filename}/{index}")
def update_highlight(
    filename: str,
    index: int,
    timing: ClipTiming
):

    # Validate filename
    if not SAFE_FILENAME.fullmatch(filename):
        raise HTTPException(
            status_code=400,
            detail="Invalid filename"
        )

    video_path = UPLOAD_DIR / filename

    highlight_file = (
        HIGHLIGHTS_DIR /
        f"{Path(filename).stem}.json"
    )

    if not video_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Original video not found"
        )

    if not highlight_file.is_file():
        raise HTTPException(
            status_code=404,
            detail="AI highlights not found"
        )

    # Load existing AI recommendations
    try:
        data = json.loads(
            highlight_file.read_text(encoding="utf-8")
        )
        highlights = data["highlights"]

    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(
            status_code=500,
            detail="Could not load highlight data"
        )

    if not 0 <= index < len(highlights):
        raise HTTPException(
            status_code=404,
            detail="Highlight index not found"
        )

    start = timing.start
    end = timing.end

    # Get original video duration
    duration = get_video_duration(video_path)

    # Validate timestamps
    if not all(math.isfinite(t) for t in (start, end)):
        raise HTTPException(
            status_code=400,
            detail="Invalid timestamps"
        )

    if not 0 <= start < end <= duration:
        raise HTTPException(
            status_code=400,
            detail="Timestamps must be within video duration"
        )

    if end - start > 60:
        raise HTTPException(
            status_code=400,
            detail="Clip cannot exceed 60 seconds"
        )

    # Prevent overlapping highlights
    for i, existing in enumerate(highlights):

        if i == index:
            continue

        existing_start = float(existing["start"])
        existing_end = float(existing["end"])

        overlaps = (
            max(start, existing_start) <
            min(end, existing_end)
        )

        if overlaps:
            raise HTTPException(
                status_code=400,
                detail="Clip overlaps another highlight"
            )

    # Save updated timestamps
    highlights[index]["start"] = round(start, 2)
    highlights[index]["end"] = round(end, 2)

    highlight_file.write_text(
        json.dumps(
            data,
            indent=4,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    return {
        "message": "Clip timestamps updated successfully!",
        "highlight": highlights[index]
    }
