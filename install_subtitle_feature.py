
from pathlib import Path
from datetime import datetime
import ast
import shutil

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "main.py"
INDEX = ROOT / "frontend" / "index.html"

if not MAIN.is_file() or not INDEX.is_file():
    raise SystemExit(
        "Run this installer from the project folder "
        "containing main.py and frontend/index.html."
    )

main = MAIN.read_text(encoding="utf-8")
html = INDEX.read_text(encoding="utf-8")

BACKEND_MARKER = "# SUBTITLE_FEATURE_BEGIN"
FRONTEND_MARKER = "// SUBTITLE_FEATURE_BEGIN"

backend = r'''

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
'''

css = r'''

/* Subtitle editing feature */
.subtitle-panel {
    margin-top: 16px;
    padding: 16px;
    background: #17243b;
    border: 1px solid #475569;
    border-radius: 10px;
}

.subtitle-panel select,
.subtitle-panel input {
    padding: 9px;
    background: #0f172a;
    color: white;
    border: 1px solid #475569;
    border-radius: 6px;
}

.subtitle-panel select {
    max-width: 100%;
    margin: 10px;
}

.subtitle-cue {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-top: 10px;
    padding: 12px;
    border: 1px solid #334155;
    border-radius: 8px;
}

.subtitle-cue input[type="number"] {
    width: 90px;
    margin: 0;
}

.subtitle-cue input[type="text"] {
    flex: 1;
    min-width: 180px;
    margin: 0;
}
'''

frontend = r'''

// SUBTITLE_FEATURE_BEGIN

function addSubtitlePanel(filename, index, box) {

    const panel = document.createElement("div");
    panel.className = "subtitle-panel";

    const openButton = document.createElement("button");
    openButton.textContent = "Edit / AI Correct Subtitles";

    const content = document.createElement("div");
    content.hidden = true;

    const description = document.createElement("p");
    description.textContent =
        "Review captions before generating Shorts. " +
        "English speech uses English text; Hindi/Hinglish " +
        "can be written using Roman letters.";

    const mode = document.createElement("select");

    [
        ["auto", "Auto"],
        ["english", "English"],
        ["romanized", "Romanized Hindi/Hinglish"]
    ].forEach(([value, title]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = title;
        mode.appendChild(option);
    });

    const aiButton = document.createElement("button");
    aiButton.textContent = "AI Correct from Audio";

    const saveButton = document.createElement("button");
    saveButton.textContent = "Save Subtitle Edits";

    const resetButton = document.createElement("button");
    resetButton.textContent = "Reset from Whisper";

    const status = document.createElement("p");
    status.className = "status";

    const rows = document.createElement("div");

    content.append(
        description,
        mode,
        aiButton,
        saveButton,
        resetButton,
        status,
        rows
    );

    panel.append(openButton, content);
    box.appendChild(panel);

    let draft = null;

    const api =
        "/subtitle-review/" +
        encodeURIComponent(filename) +
        "/" + index;

    async function call(url, method = "GET", data = null) {
        const options = { method };

        if (data !== null) {
            options.headers = {
                "Content-Type": "application/json"
            };
            options.body = JSON.stringify(data);
        }

        const response = await fetch(url, options);
        const result = await response.json();

        if (!response.ok) {
            const message =
                typeof result.detail === "string"
                    ? result.detail
                    : JSON.stringify(result.detail);

            throw new Error(message || "Request failed");
        }

        return result;
    }

    function drawCues() {
        rows.replaceChildren();

        draft.cues.forEach(cue => {
            const row = document.createElement("div");
            row.className = "subtitle-cue";
            row.dataset.id = cue.id;

            const start = document.createElement("input");
            start.type = "number";
            start.step = "0.01";
            start.min = "0";
            start.max = String(draft.duration);
            start.value = cue.start;
            start.dataset.role = "start";

            const end = document.createElement("input");
            end.type = "number";
            end.step = "0.01";
            end.min = "0";
            end.max = String(draft.duration);
            end.value = cue.end;
            end.dataset.role = "end";

            const text = document.createElement("input");
            text.type = "text";
            text.value = cue.text;
            text.dataset.role = "text";

            const play = document.createElement("button");
            play.textContent = "Play";

            play.onclick = async () => {
                const a = Number(start.value);
                const b = Number(end.value);

                if (!(a >= 0 && b > a)) {
                    status.textContent =
                        "Invalid subtitle timing.";
                    return;
                }

                videoPlayer.pause();

                videoPlayer.currentTime =
                    draft.video_start + a;

                activeClipEnd =
                    draft.video_start + b;

                document
                    .getElementById("previewCard")
                    .scrollIntoView({
                        behavior: "smooth"
                    });

                try {
                    await videoPlayer.play();
                } catch (error) {
                    status.textContent =
                        "Could not play preview: " +
                        error.message;
                }
            };

            row.append(start, end, text, play);
            rows.appendChild(row);
        });
    }

    function collectCues() {
        return Array.from(
            rows.querySelectorAll(".subtitle-cue")
        ).map(row => ({
            id: Number(row.dataset.id),
            start: Number(
                row.querySelector('[data-role="start"]').value
            ),
            end: Number(
                row.querySelector('[data-role="end"]').value
            ),
            text: row.querySelector(
                '[data-role="text"]'
            ).value
        }));
    }

    async function loadDraft() {
        status.textContent =
            "Loading transcript for this highlight...";

        draft = await call(api);
        mode.value = draft.mode || "auto";

        drawCues();

        status.textContent =
            `${draft.cues.length} captions loaded.`;
    }

    openButton.onclick = async () => {
        content.hidden = !content.hidden;

        if (content.hidden || draft) return;

        try {
            await loadDraft();
        } catch (error) {
            status.textContent =
                "Error: " + error.message;
        }
    };

    saveButton.onclick = async () => {
        if (!draft) return;

        saveButton.disabled = true;
        status.textContent = "Saving subtitle edits...";

        try {
            const result = await call(
                api,
                "PUT",
                {
                    mode: mode.value,
                    cues: collectCues()
                }
            );

            draft.cues = result.cues;

            document
                .getElementById("shortsCard")
                .hidden = true;

            status.textContent =
                "Saved! Generate Shorts to apply " +
                "these captions using FFmpeg.";

        } catch (error) {
            status.textContent =
                "Save error: " + error.message;
        } finally {
            saveButton.disabled = false;
        }
    };

    aiButton.onclick = async () => {
        if (!draft) return;

        if (!confirm(
            "Gemini will replace the current caption text. " +
            "Save manual edits first if needed. Continue?"
        )) return;

        aiButton.disabled = true;
        status.textContent =
            "Gemini is checking the original audio...";

        try {
            const result = await call(
                api + "/ai",
                "POST",
                { mode: mode.value }
            );

            draft.cues = result.cues;
            drawCues();

            document
                .getElementById("shortsCard")
                .hidden = true;

            status.textContent =
                "AI correction finished. Review text " +
                "and timing before generating Shorts.";

        } catch (error) {
            status.textContent =
                "AI correction error: " + error.message;
        } finally {
            aiButton.disabled = false;
        }
    };

    resetButton.onclick = async () => {
        if (!confirm(
            "Reset captions from Whisper? " +
            "A backup of saved edits will be kept."
        )) return;

        resetButton.disabled = true;

        try {
            draft = await call(
                api + "/reset",
                "POST"
            );

            mode.value = draft.mode;
            drawCues();

            status.textContent =
                "Whisper captions restored.";

        } catch (error) {
            status.textContent =
                "Reset error: " + error.message;
        } finally {
            resetButton.disabled = false;
        }
    };
}

// SUBTITLE_FEATURE_END
'''

# ------------------------------------------
# Validate the expected existing code
# ------------------------------------------

old_render = '''    clips = create_shorts(
        filename,
        selected,
        transcript["segments"],
        mode=mode,
    )'''

new_render = '''    reviewed_segments = merge_reviewed_subtitles(
        filename,
        selected,
        transcript["segments"],
    )

    clips = create_shorts(
        filename,
        selected,
        reviewed_segments,
        mode=mode,
    )'''

if BACKEND_MARKER not in main:
    if old_render not in main:
        raise SystemExit(
            "Could not find the original Short rendering "
            "function. No files were changed."
        )

    main = main.replace(
        old_render,
        new_render,
        1,
    )

    # The existing backend previously transcribed
    # only the first 3 selected highlights.
    main = main.replace(
        "for clip in highlights[:3]:",
        "for clip in highlights[:6]:",
        1,
    )

    # Make the combine endpoint respect the
    # updated video editor's Short limit.
    main = main.replace(
        '1 if mode == "fast" else 3,',
        'settings(mode)["limit"],',
        1,
    )

    main += "\n" + backend

if FRONTEND_MARKER not in html:
    old_insert = "            list.appendChild(box);"

    if old_insert not in html:
        raise SystemExit(
            "Could not find the highlight card builder. "
            "No files were changed."
        )

    html = html.replace(
        old_insert,
        old_insert + "\n" +
        "            addSubtitlePanel(filename, index, box);",
        1,
    )

    html = html.replace(
        "</style>",
        css + "\n</style>",
        1,
    )

    html = html.replace(
        "</script>",
        frontend + "\n</script>",
        1,
    )

# Check Python syntax before touching files.
ast.parse(main)

# Back up the original versions.
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

shutil.copy2(
    MAIN,
    ROOT / f"main_before_subtitles_{stamp}.py",
)

shutil.copy2(
    INDEX,
    INDEX.parent /
    f"index_before_subtitles_{stamp}.html",
)

MAIN.write_text(main, encoding="utf-8")
INDEX.write_text(html, encoding="utf-8")

print("SUCCESS: Subtitle feature installed.")
print("Updated: main.py")
print("Updated: frontend/index.html")
print("Backups created.")
print("Restart FastAPI and open /dashboard.")
