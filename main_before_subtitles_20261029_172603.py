
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import traceback

from functools import lru_cache
from pathlib import Path
from uuid import uuid4
from typing import Literal

from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Query,
)
from fastapi.responses import FileResponse
from faster_whisper import WhisperModel
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env", override=True)

from gemini_analyzer import (
    analyze_video,
    get_video_duration,
    MODEL_NAME,
)
from video_editor import (
    create_shorts,
    combine_shorts,
    settings,
)


UPLOADS = BASE_DIR / "uploads"
TRANSCRIPTS = BASE_DIR / "transcripts"
HIGHLIGHTS = BASE_DIR / "highlights"
CLIPS = BASE_DIR / "clips"
FRONTEND = BASE_DIR / "frontend"

for folder in (
    UPLOADS,
    TRANSCRIPTS,
    HIGHLIGHTS,
    CLIPS,
    FRONTEND,
):
    folder.mkdir(parents=True, exist_ok=True)


app = FastAPI(
    title="AI Video Editing Agent",
    version="3.0.0",
)

VIDEO_PATTERN = re.compile(
    r"[0-9a-f]{32}\.mp4"
)

CLIP_PATTERN = re.compile(
    r"[0-9a-f]{32}_(?:"
    r"clip_[1-9][0-9]*(?:_(?:fast|quality))?"
    r"|combined_(?:fast|quality))\.mp4"
)

WHISPER_MODEL = (
    os.getenv("WHISPER_MODEL", "base.en")
    .strip() or "base.en"
)


# ==========================================
# HELPERS
# ==========================================

def validate_video(filename):
    if not VIDEO_PATTERN.fullmatch(filename):
        raise HTTPException(
            400, "Invalid MP4 filename."
        )

    path = UPLOADS / filename

    if not path.is_file():
        raise HTTPException(
            404, "Uploaded video not found."
        )

    return path


def json_path(folder, filename, suffix=""):
    return (
        folder
        / f"{Path(filename).stem}{suffix}.json"
    )


def load_cached(path, filename, key):
    if not path.is_file():
        return None

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None

    if (
        not isinstance(data, dict)
        or data.get("filename") != filename
        or not isinstance(data.get(key), list)
    ):
        return None

    return data


def save_data(path, data):
    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@lru_cache(maxsize=1)
def whisper():
    print(f"Loading Whisper {WHISPER_MODEL}")

    return WhisperModel(
        WHISPER_MODEL,
        device="cpu",
        compute_type="int8",
    )


def has_audio(video_path):
    probe = shutil.which("ffprobe")

    if not probe:
        raise RuntimeError(
            "ffprobe is required. Install FFmpeg."
        )

    result = subprocess.run(
        [
            probe,
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        errors="replace",
    )

    return (
        result.returncode == 0
        and bool(result.stdout.strip())
    )


def transcribe_ranges(video_path, ranges):
    """
    Each range is (start, end).
    End=None means continue to the end.

    Output timestamps are in ORIGINAL
    video time, not temporary audio time.
    """
    if not has_audio(video_path):
        return []

    ffmpeg = shutil.which("ffmpeg")

    if not ffmpeg:
        raise RuntimeError("FFmpeg not found.")

    model = whisper()
    output = []

    with tempfile.TemporaryDirectory(
        prefix="speech_",
        dir=BASE_DIR,
    ) as temp_folder:
        temp_folder = Path(temp_folder)

        for index, (start, end) in enumerate(ranges):
            wav_file = (
                temp_folder / f"audio_{index}.wav"
            )

            command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-ss", str(start),
                "-i", str(video_path),
            ]

            if end is not None:
                command.extend([
                    "-t", str(end - start)
                ])

            command.extend([
                "-map", "0:a:0",
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                "-c:a", "pcm_s16le",
                str(wav_file),
            ])

            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=300,
            )

            if process.returncode != 0:
                raise RuntimeError(
                    "Audio extraction failed:\n"
                    + process.stderr[-1500:]
                )

            segments, _ = model.transcribe( 
                str(wav_file),
                language="hi",
                task="transcribe",
                multilingual=False,
                beam_size=3,
                temperature=0.0,
                vad_filter=True,
                condition_on_previous_text=False,
                word_timestamps=True,
            )

            for segment in segments:
                words = []

                for word in segment.words or []:
                    if (
                        word.start is None
                        or word.end is None
                    ):
                        continue

                    words.append({
                        "start": round(
                            start + word.start, 2
                        ),
                        "end": round(
                            start + word.end, 2
                        ),
                        "word": word.word,
                    })

                output.append({
                    "start": round(
                        start + segment.start, 2
                    ),
                    "end": round(
                        start + segment.end, 2
                    ),
                    "text": segment.text.strip(),
                    "words": words,
                })

    output.sort(key=lambda s: s["start"])
    return output


def get_full_transcript(filename, force=False):
    path = json_path(TRANSCRIPTS, filename)

    if not force:
        existing = load_cached(
            path, filename, "segments"
        )
        if existing is not None:
            return {**existing, "cached": True}

    video_path = validate_video(filename)

    segments = transcribe_ranges(
        video_path,
        [(0.0, None)],
    )

    result = {
        "filename": filename,
        "language": "en",
        "model": WHISPER_MODEL,
        "coverage": "full",
        "segments": segments,
        "full_text": " ".join(
            s["text"] for s in segments
        ),
    }

    save_data(path, result)

    return {**result, "cached": False}


def get_selected_transcript(filename, highlights):
    # A saved full transcript can serve all clips.
    full_path = json_path(
        TRANSCRIPTS, filename
    )

    full = load_cached(
        full_path, filename, "segments"
    )

    if full is not None:
        return {**full, "cached": True}

    video_path = validate_video(filename)
    duration = get_video_duration(video_path)

    ranges = []

    for clip in highlights[:3]:
        start = float(clip["start"])
        end = min(
            float(clip["end"]),
            start + 60,
            duration,
        )

        if not (
            math.isfinite(start)
            and math.isfinite(end)
            and 0 <= start < end
        ):
            raise ValueError(
                "Invalid Gemini highlight timestamps."
            )

        ranges.append([
            round(start, 2),
            round(end, 2),
        ])

    path = json_path(
        TRANSCRIPTS,
        filename,
        ".selected",
    )

    existing = load_cached(
        path, filename, "segments"
    )

    if (
        existing is not None
        and existing.get("ranges") == ranges
    ):
        return {**existing, "cached": True}

    print(
        "Transcribing selected highlights only..."
    )

    segments = transcribe_ranges(
        video_path,
        ranges,
    )

    result = {
        "filename": filename,
        "language": "en",
        "model": WHISPER_MODEL,
        "coverage": "selected",
        "ranges": ranges,
        "segments": segments,
        "full_text": " ".join(
            s["text"] for s in segments
        ),
    }

    save_data(path, result)

    return {**result, "cached": False}


# ==========================================
# BASIC ROUTES
# ==========================================

@app.get("/")
def home():
    return {
        "status": "running",
        "project": "AI Video Editing Agent",
    }


@app.get("/health")
def health():
    return {
        "status": "running",
        "ffmpeg_found": bool(shutil.which("ffmpeg")),
        "ffprobe_found": bool(shutil.which("ffprobe")),
        "whisper_model": WHISPER_MODEL,
    }


@app.get("/dashboard")
def dashboard():
    path = FRONTEND / "index.html"

    if not path.is_file():
        raise HTTPException(
            404, "Dashboard file not found."
        )

    return FileResponse(path)


# ==========================================
# UPLOAD
# ==========================================

@app.post("/upload")
def upload(file: UploadFile = File(...)):
    extension = Path(
        file.filename or ""
    ).suffix.lower()

    if extension != ".mp4":
        raise HTTPException(
            400,
            "This stable backend currently accepts MP4 only.",
        )

    temporary = (
        UPLOADS / f"{uuid4().hex}.upload"
    )

    total = 0
    digest = hashlib.sha256()

    try:
        with temporary.open("wb") as destination:
            while True:
                chunk = file.file.read(1024 * 1024)

                if not chunk:
                    break

                total += len(chunk)

                if total > 200 * 1024 * 1024:
                    raise HTTPException(
                        413, "Maximum upload size is 200 MB."
                    )

                digest.update(chunk)
                destination.write(chunk)

        if total == 0:
            raise HTTPException(
                400, "Empty upload."
            )

        filename = digest.hexdigest()[:32] + ".mp4"
        final = UPLOADS / filename
        reused = final.is_file()

        if reused:
            temporary.unlink(missing_ok=True)
        else:
            temporary.replace(final)

        return {
            "filename": filename,
            "message": "Video uploaded successfully!",
            "reused_upload": reused,
            "size_mb": round(total / 1048576, 2),
        }

    finally:
        temporary.unlink(missing_ok=True)
        file.file.close()


@app.get("/videos/{filename}")
def video(filename: str):
    return FileResponse(
        validate_video(filename),
        media_type="video/mp4",
    )


# ==========================================
# WHISPER
# ==========================================

@app.post("/transcribe/{filename}")
def transcribe(
    filename: str,
    force: bool = Query(False),
):
    validate_video(filename)

    try:
        return get_full_transcript(
            filename,
            force,
        )

    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            500, f"Whisper failed: {error}"
        ) from error


# ==========================================
# GEMINI
# ==========================================

@app.post("/highlights/{filename}")
def highlights(
    filename: str,
    force: bool = Query(False),
):
    video_path = validate_video(filename)
    output_path = json_path(
        HIGHLIGHTS, filename
    )

    if not force:
        cached = load_cached(
            output_path, filename, "highlights"
        )

        if cached and cached["highlights"]:
            return {**cached, "cached": True}

    transcript = load_cached(
        json_path(TRANSCRIPTS, filename),
        filename,
        "segments",
    )

    context = (
        transcript["segments"]
        if transcript is not None
        else None
    )

    try:
        selected = analyze_video(
            video_path,
            context,
        )

        result = {
            "filename": filename,
            "model": MODEL_NAME,
            "highlights": selected,
        }

        save_data(output_path, result)

        return {**result, "cached": False}

    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            502, f"Gemini failed: {error}"
        ) from error


# ==========================================
# EDIT HIGHLIGHT TIMESTAMPS
# ==========================================

class ClipTiming(BaseModel):
    start: float
    end: float


@app.post("/update-highlight/{filename}/{index}")
def update_highlight(
    filename: str,
    index: int,
    timing: ClipTiming,
):
    video_path = validate_video(filename)
    path = json_path(HIGHLIGHTS, filename)

    data = load_cached(
        path, filename, "highlights"
    )

    if data is None:
        raise HTTPException(
            404, "Highlights not found."
        )

    clips = data["highlights"]

    if not 0 <= index < len(clips):
        raise HTTPException(
            404, "Clip index not found."
        )

    start = timing.start
    end = timing.end
    duration = get_video_duration(video_path)

    if not all(math.isfinite(x) for x in (start, end)):
        raise HTTPException(
            400, "Invalid timestamps."
        )

    if not 0 <= start < end <= duration:
        raise HTTPException(
            400, "Times are outside video duration."
        )

    if end - start > 60:
        raise HTTPException(
            400, "Maximum clip length is 60 seconds."
        )

    for i, other in enumerate(clips):
        if i == index:
            continue

        if (
            max(start, float(other["start"]))
            < min(end, float(other["end"]))
        ):
            raise HTTPException(
                400, "Highlights cannot overlap."
            )

    clips[index]["start"] = round(start, 2)
    clips[index]["end"] = round(end, 2)

    save_data(path, data)

    return {
        "message": "Clip timestamps updated!",
        "highlight": clips[index],
    }


# ==========================================
# RENDER HELPERS
# ==========================================

def render_video(filename, mode):
    validate_video(filename)

    data = load_cached(
        json_path(HIGHLIGHTS, filename),
        filename,
        "highlights",
    )

    if not data or not data["highlights"]:
        raise HTTPException(
            400, "Generate Gemini highlights first."
        )

    selected = data["highlights"]

    transcript = get_selected_transcript(
        filename,
        selected,
    )

    clips = create_shorts(
        filename,
        selected,
        transcript["segments"],
        mode=mode,
    )

    return {
        "message": "MP4 Shorts generated successfully!",
        "clips": clips,
        "transcript_cached": transcript["cached"],
    }


# ==========================================
# EXISTING DASHBOARD RENDER ROUTE
# ==========================================

@app.post("/generate-clips/{filename}")
def generate_clips(
    filename: str,
    mode: Literal["fast", "quality"] | None = None,
):
    try:
        selected_mode = (
            mode or settings()["mode"]
        )

        return render_video(
            filename,
            selected_mode,
        )

    except HTTPException:
        raise

    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            500, f"Rendering failed: {error}"
        ) from error


# ==========================================
# NEW ONE-REQUEST PROCESS ROUTE
# ==========================================

@app.post("/process/{filename}")
def process_video(
    filename: str,
    mode: Literal["fast", "quality"] = "fast",
    force_gemini: bool = False,
    combine: bool = False,
):
    validate_video(filename)

    # 1. Gemini highlights, cached when possible.
    ai_result = highlights(
        filename,
        force=force_gemini,
    )

    # 2. Whisper selected portions + FFmpeg.
    rendered = generate_clips(
        filename,
        mode=mode,
    )

    result = {
        "message": "Processing completed.",
        "gemini_cached": ai_result["cached"],
        **rendered,
    }

    # 3. Compilation is optional.
    # If it fails, individual Shorts are retained.
    if combine:
        try:
            result["combined"] = combine_shorts(
                filename,
                rendered["clips"],
                mode,
            )
        except Exception as error:
            result["combine_error"] = str(error)

    return result


# ==========================================
# COMBINE EXISTING SHORTS
# ==========================================

@app.post("/combine-clips/{filename}")
def combine_existing(
    filename: str,
    mode: Literal["fast", "quality"] = "quality",
):
    validate_video(filename)

    data = load_cached(
        json_path(HIGHLIGHTS, filename),
        filename,
        "highlights",
    )

    if not data or not data["highlights"]:
        raise HTTPException(
            400, "No highlights available."
        )

    limit = min(
        len(data["highlights"]),
        1 if mode == "fast" else 3,
    )

    stem = Path(filename).stem

    clips = [
        {
            "filename": (
                f"{stem}_clip_{i}_{mode}.mp4"
            )
        }
        for i in range(1, limit + 1)
    ]

    try:
        return combine_shorts(
            filename,
            clips,
            mode,
        )
    except Exception as error:
        raise HTTPException(
            500, f"Combining failed: {error}"
        ) from error


# ==========================================
# SERVE OUTPUT VIDEO
# ==========================================

@app.get("/clips/{filename}")
def serve_clip(filename: str):
    if not CLIP_PATTERN.fullmatch(filename):
        raise HTTPException(
            400, "Invalid generated clip filename."
        )

    path = CLIPS / filename

    if not path.is_file():
        raise HTTPException(
            404, "Generated clip not found."
        )

    return FileResponse(
        path,
        media_type="video/mp4",
        content_disposition_type="inline",
    )
