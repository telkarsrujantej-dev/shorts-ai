
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

    for clip in highlights[:6]:
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

    reviewed_segments = merge_reviewed_subtitles(
        filename,
        selected,
        transcript["segments"],
    )

    clips = create_shorts(
        filename,
        selected,
        reviewed_segments,
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
        settings(mode)["limit"],
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



# SUBTITLE_FEATURE_BEGIN
# AI-assisted subtitle review for existing Shorts.

from google import genai
from google.genai import types
from video_editor import caption_events

SUBTITLE_REVIEWS = BASE_DIR / "subtitle_reviews"
SUBTITLE_REVIEWS.mkdir(parents=True, exist_ok=True)


class SubtitleCueEdit(BaseModel):
    id: int
    start: float
    end: float
    text: str


class SubtitleSaveBody(BaseModel):
    mode: Literal["auto", "english", "romanized"] = "auto"
    cues: list[SubtitleCueEdit]


class SubtitleAIBody(BaseModel):
    mode: Literal["auto", "english", "romanized"] = "auto"


class AISubtitleCue(BaseModel):
    id: int
    text: str


class AISubtitleResponse(BaseModel):
    cues: list[AISubtitleCue]


def subtitle_review_path(filename, index):
    return SUBTITLE_REVIEWS / (
        f"{Path(filename).stem}_clip_{index + 1}.json"
    )


def subtitle_clip_info(filename, index):
    validate_video(filename)

    data = load_cached(
        json_path(HIGHLIGHTS, filename),
        filename,
        "highlights",
    )

    if not data or not 0 <= index < len(data["highlights"]):
        raise HTTPException(
            404,
            "Highlight not found. Generate highlights first.",
        )

    clip = data["highlights"][index]
    start = float(clip["start"])
    end = min(float(clip["end"]), start + 60)

    if not all(math.isfinite(x) for x in (start, end)):
        raise HTTPException(400, "Invalid highlight timestamps.")

    if not 0 <= start < end:
        raise HTTPException(400, "Invalid highlight duration.")

    return data["highlights"], start, end


def save_subtitle_doc(filename, index, doc):
    path = subtitle_review_path(filename, index)
    temp = path.with_name(
        f"{path.stem}_{uuid4().hex}.tmp"
    )

    try:
        temp.write_text(
            json.dumps(
                doc,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def get_subtitle_doc(filename, index):
    clips, start, end = subtitle_clip_info(
        filename, index
    )

    path = subtitle_review_path(filename, index)
    saved = load_cached(path, filename, "cues")

    if saved is not None:
        if (
            abs(saved.get("video_start", -1) - start) > 0.01
            or abs(saved.get("video_end", -1) - end) > 0.01
        ):
            raise HTTPException(
                409,
                "Highlight times changed. Use Reset from Whisper "
                "to rebuild this subtitle draft.",
            )

        return saved

    transcript = get_selected_transcript(
        filename, clips
    )

    events, word_timed = caption_events(
        transcript["segments"], start, end
    )

    cues = []
    duration = end - start

    for cue_start, cue_end, text in events:
        a = round(max(0, cue_start - start), 2)
        b = round(min(duration, cue_end - start), 2)

        if cues:
            a = max(a, cues[-1]["end"])

        text = " ".join(str(text).split())

        if b <= a or not text:
            continue

        cues.append({
            "id": len(cues),
            "start": a,
            "end": b,
            "text": text,
            "original_text": text,
        })

    if not cues:
        raise HTTPException(
            422,
            "No speech captions found for this highlight.",
        )

    doc = {
        "filename": filename,
        "index": index,
        "video_start": start,
        "video_end": end,
        "duration": round(duration, 2),
        "mode": "auto",
        "ai_reviewed": False,
        "word_timed_original": word_timed,
        "cues": cues,
    }

    save_subtitle_doc(filename, index, doc)
    return doc


@app.get("/subtitle-review/{filename}/{index}")
def get_subtitle_review(filename: str, index: int):
    return get_subtitle_doc(filename, index)


@app.put("/subtitle-review/{filename}/{index}")
def save_subtitle_review(
    filename: str,
    index: int,
    body: SubtitleSaveBody,
):
    doc = get_subtitle_doc(filename, index)

    if len(body.cues) != len(doc["cues"]):
        raise HTTPException(
            400,
            "The subtitle cue count cannot be changed yet.",
        )

    if len(body.cues) > 200:
        raise HTTPException(400, "Too many subtitle cues.")

    updated = []

    for old, new in zip(doc["cues"], body.cues):
        if old["id"] != new.id:
            raise HTTPException(
                400, "Subtitle cue IDs must remain in order."
            )

        start = new.start
        end = new.end
        text = " ".join(new.text.split())

        if not all(math.isfinite(x) for x in (start, end)):
            raise HTTPException(
                400, f"Invalid time for subtitle {new.id}."
            )

        if not 0 <= start < end <= doc["duration"] + 0.01:
            raise HTTPException(
                400,
                f"Subtitle {new.id} is outside the clip.",
            )

        if not text or len(text) > 500:
            raise HTTPException(
                400,
                f"Subtitle {new.id} has invalid text.",
            )

        updated.append({
            **old,
            "start": round(start, 2),
            "end": round(end, 2),
            "text": text,
        })

    for previous, current in zip(
        updated, updated[1:]
    ):
        if current["start"] < previous["end"]:
            raise HTTPException(
                400,
                "Subtitle timings must not overlap.",
            )

    doc["cues"] = updated
    doc["mode"] = body.mode

    save_subtitle_doc(filename, index, doc)

    return {
        "message": "Subtitle edits saved successfully.",
        "cues": updated,
    }


@app.post("/subtitle-review/{filename}/{index}/reset")
def reset_subtitle_review(filename: str, index: int):
    subtitle_clip_info(filename, index)

    path = subtitle_review_path(filename, index)

    if path.is_file():
        backup = path.with_name(
            f"{path.stem}_{uuid4().hex}.backup.json"
        )
        shutil.copy2(path, backup)
        path.unlink()

    return get_subtitle_doc(filename, index)


@app.post("/subtitle-review/{filename}/{index}/ai")
def ai_correct_subtitles(
    filename: str,
    index: int,
    body: SubtitleAIBody,
):
    doc = get_subtitle_doc(filename, index)

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise HTTPException(
            400, "GEMINI_API_KEY is missing from .env."
        )

    ffmpeg = shutil.which("ffmpeg")

    if not ffmpeg:
        raise HTTPException(500, "FFmpeg was not found.")

    video = validate_video(filename)

    original = [
        {
            "id": cue["id"],
            "start": cue["start"],
            "end": cue["end"],
            "text": cue["text"],
        }
        for cue in doc["cues"]
    ]

    prompt = f"""
You are an expert multilingual subtitle proofreader.

Listen to the ORIGINAL AUDIO attached to this request.
Compare it with the Whisper-generated subtitles.

The audio may contain English, Hindi or Hinglish.

OUTPUT MODE: {body.mode}

RULES:
- ENGLISH: For English speech, write English captions.
- ROMANIZED: Write Hindi/Hinglish using Latin letters.
- AUTO: English speech gets English captions.
  Hindi/Hinglish speech gets Romanized captions.
- Romanized means transliteration, NOT English translation.
- Keep actual English words in mixed-language speech.
- Correct misheard words using the original audio.
- Do not invent speech, translate meanings, or add facts.
- Keep the same number of subtitle cues.
- Keep every cue's original ID.
- Do not return timestamps.
- Correct punctuation and wording only.
- If uncertain, keep the original words.
- Respect the approximate speech boundaries
  represented by the cue timestamps.

SUBTITLE CUES:
{json.dumps(original, ensure_ascii=False)}

Return JSON with exactly:
{{"cues":[{{"id":0,"text":"corrected text"}}]}}
Include all original IDs.
"""

    with tempfile.TemporaryDirectory(
        prefix="subtitle_audio_",
        dir=BASE_DIR,
    ) as temporary:
        audio_file = (
            Path(temporary) / "clip_audio.wav"
        )

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-ss", str(doc["video_start"]),
            "-i", str(video),
            "-t", str(doc["duration"]),
            "-map", "0:a:0",
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            str(audio_file),
        ]

        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=180,
        )

        if process.returncode != 0:
            raise HTTPException(
                422,
                "Audio extraction failed. "
                "Check that the source video has speech audio.",
            )

        client = genai.Client(api_key=api_key)

        try:
            response = client.models.generate_content(
                model=os.getenv(
                    "SUBTITLE_AI_MODEL",
                    MODEL_NAME,
                ),
                contents=[
                    types.Part.from_bytes(
                        data=audio_file.read_bytes(),
                        mime_type="audio/wav",
                    ),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=AISubtitleResponse,
                    temperature=0.1,
                ),
            )

            parsed = (
                AISubtitleResponse.model_validate_json(
                    response.text or ""
                )
            )

        except Exception as error:
            traceback.print_exc()
            raise HTTPException(
                502,
                "Gemini subtitle correction failed. "
                "Your existing captions were not changed. "
                "You can retry or edit them manually.",
            ) from error

        finally:
            client.close()

    corrections = {
        cue.id: cue.text.strip()
        for cue in parsed.cues
    }

    expected_ids = {
        cue["id"] for cue in doc["cues"]
    }

    if (
        len(parsed.cues) != len(expected_ids)
        or set(corrections) != expected_ids
        or any(not value for value in corrections.values())
    ):
        raise HTTPException(
            502,
            "Gemini returned incomplete subtitles. "
            "The original captions are unchanged.",
        )

    if body.mode == "romanized":
        script_pattern = re.compile(
            r"[\u0600-\u06FF\u0900-\u097F]"
        )

        if any(
            script_pattern.search(text)
            for text in corrections.values()
        ):
            raise HTTPException(
                502,
                "Gemini returned Hindi/Urdu script instead "
                "of Romanized captions. Nothing was saved.",
            )

    for cue in doc["cues"]:
        cue["text"] = corrections[cue["id"]]

    doc["mode"] = body.mode
    doc["ai_reviewed"] = True

    save_subtitle_doc(filename, index, doc)

    return {
        "message": "AI-corrected subtitles saved for review.",
        "cues": doc["cues"],
    }


def merge_reviewed_subtitles(
    filename,
    highlights,
    original_segments,
):
    """
    Apply manually reviewed caption text and timing
    without changing the original Whisper transcript.

    The existing video_editor.caption_events() function
    receives each reviewed cue as one timed phrase.
    """

    replacements = []
    reviewed_ranges = []

    for index, clip in enumerate(highlights):
        doc = load_cached(
            subtitle_review_path(filename, index),
            filename,
            "cues",
        )

        if doc is None:
            continue

        start = float(clip["start"])
        end = min(float(clip["end"]), start + 60)

        if (
            abs(doc.get("video_start", -1) - start) > 0.01
            or abs(doc.get("video_end", -1) - end) > 0.01
        ):
            continue

        reviewed_ranges.append((start, end))

        for cue in doc["cues"]:
            a = start + float(cue["start"])
            b = start + float(cue["end"])
            text = cue["text"]

            if b <= a or not text:
                continue

            replacements.append({
                "start": a,
                "end": b,
                "text": text,
                "words": [{
                    "start": a,
                    "end": b,
                    "word": text,
                }],
            })

    if not replacements:
        return original_segments

    retained = []

    for segment in original_segments:
        s = float(segment["start"])
        e = float(segment["end"])

        covered = any(
            e > a and s < b
            for a, b in reviewed_ranges
        )

        if not covered:
            retained.append(segment)

    result = retained + replacements

    result.sort(key=lambda segment: segment["start"])
    return result

# SUBTITLE_FEATURE_END
