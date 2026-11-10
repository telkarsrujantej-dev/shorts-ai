
import math
import os
import shutil
import subprocess
import tempfile
import textwrap
import time

from pathlib import Path
from dotenv import dotenv_values
import re
from transcription_service import normalize_caption_text
# HINDI_ROMAN_RENDER_FIX



BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
CLIPS_DIR = BASE_DIR / "clips"
CAPTION_DIR = BASE_DIR / "clip_captions"

for folder in (UPLOAD_DIR, CLIPS_DIR, CAPTION_DIR):
    folder.mkdir(parents=True, exist_ok=True)


# ==========================================
# 1. VIDEO RENDER SETTINGS
# ==========================================

def settings(mode=None):
    env = {} if os.getenv("AI_VIDEO_AGENT_LOAD_ENV", "1") == "0" else dotenv_values(BASE_DIR / ".env")

    selected = (
        mode
        or os.getenv("VIDEO_RENDER_MODE")
        or env.get("VIDEO_RENDER_MODE")
        or "fast"
    ).strip().lower()

    if selected not in ("fast", "quality"):
        raise ValueError("Mode must be fast or quality.")

    # UPDATED:
    # Both modes now generate up to 6 Shorts.
    # Fast mode no longer cuts every Short at 10s.

    if selected == "fast":
        return {
            "mode": "fast",
            "width": 360,
            "height": 640,
            "fps": 20,
            "preset": "ultrafast",
            "crf": 30,
            "limit": 6,
            "seconds": 60,
        }

    return {
        "mode": "quality",
        "width": 720,
        "height": 1280,
        "fps": 30,
        "preset": "veryfast",
        "crf": 23,
        "limit": 6,
        "seconds": 60,
    }


# ==========================================
# 2. FFMPEG HELPERS
# ==========================================

def ffmpeg_path():
    executable = shutil.which("ffmpeg")

    if not executable:
        raise RuntimeError(
            "FFmpeg is not installed or not in PATH."
        )

    return executable


def execute(command, timeout=600):
    result = subprocess.run(
        command,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg failed:\n" + result.stderr[-3500:]
        )

    return result


# ==========================================
# 3. SUBTITLE HELPERS
# ==========================================

def subtitle_time(seconds):
    ticks = max(0, round(float(seconds) * 100))

    hours, ticks = divmod(ticks, 360000)
    minutes, ticks = divmod(ticks, 6000)
    seconds, centiseconds = divmod(ticks, 100)

    return (
        f"{hours}:{minutes:02d}:"
        f"{seconds:02d}.{centiseconds:02d}"
    )


def safe_text(value):
    text = str(value or "")

    text = normalize_caption_text(text)

    for char in ("\\", "{", "}"):
        text = text.replace(char, "")

    return " ".join(text.split())


# ==========================================
# 4. GENERATE TIMED CAPTION EVENTS
# ==========================================

def caption_events(segments, clip_start, clip_end):
    events = []
    word_timed = False

    for segment in segments or []:
        try:
            s = float(segment["start"])
            e = float(segment["end"])
        except (KeyError, ValueError, TypeError):
            continue

        if not (
            math.isfinite(s)
            and math.isfinite(e)
            and e > s
        ):
            continue

        if e <= clip_start or s >= clip_end:
            continue

        raw_words = segment.get("words") or []
        words = []

        for word in raw_words:
            try:
                a = float(word["start"])
                b = float(word["end"])
                text = safe_text(word["word"])
            except (KeyError, ValueError, TypeError):
                continue

            if not (
                math.isfinite(a)
                and math.isfinite(b)
            ):
                continue

            a = max(a, clip_start)
            b = min(b, clip_end)

            if a < b and text:
                words.append((a, b, text))

        if words:
            word_timed = True
            words.sort(key=lambda item: item[0])

            group = []

            def flush():
                if not group:
                    return

                start = group[0][0]
                end = group[-1][1]
                text = " ".join(x[2] for x in group)

                if end > start:
                    events.append((start, end, text))

            for word in words:
                if group:
                    gap = word[0] - group[-1][1]
                    span = word[1] - group[0][0]

                    if (
                        len(group) >= 5
                        or gap > 0.7
                        or span > 2.8
                    ):
                        flush()
                        group = []

                group.append(word)

            flush()
            continue


        # Fallback for transcripts that do not
        # contain word-level timestamps.

        text = safe_text(segment.get("text", ""))
        start = max(s, clip_start)
        end = min(e, clip_end)

        if not text or end <= start:
            continue

        if segment.get("caption_cue"):
            events.append((start, end, text))
            continue

        tokens = text.split()

        groups = [
            tokens[i:i + 5]
            for i in range(0, len(tokens), 5)
        ]

        for i, group in enumerate(groups):
            a = (
                start
                + (end - start) * i / len(groups)
            )

            b = (
                start
                + (end - start) * (i + 1) / len(groups)
            )

            events.append(
                (a, b, " ".join(group))
            )

    events.sort(key=lambda item: item[0])

    return events, word_timed


# ==========================================
# 5. CREATE ASS SUBTITLE FILE
# ==========================================

def create_captions(
    path,
    segments,
    clip_start,
    clip_end,
    width,
    height,
):
    events, word_timed = caption_events(
        segments,
        clip_start,
        clip_end,
    )

    if not events:
        path.unlink(missing_ok=True)
        return False, False

    font_size = 27 if width == 360 else 48
    margin = 95 if height == 640 else 190

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,25,25,{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []

    for start, end, caption in events:
        a = max(0, start - clip_start)

        b = min(
            clip_end - clip_start,
            end - clip_start,
        )

        if b <= a:
            continue

        wrapped = r"\N".join(
            textwrap.wrap(
                caption,
                width=20,
                break_long_words=False,
            )
        )

        lines.append(
            f"Dialogue: 0,{subtitle_time(a)},"
            f"{subtitle_time(b)},Default,,0,0,0,,"
            f"{wrapped}"
        )

    if not lines:
        path.unlink(missing_ok=True)
        return False, False

    path.write_text(
        header + "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    return True, word_timed


# ==========================================
# 6. GENERATE MULTIPLE MP4 SHORTS
# ==========================================

def create_shorts(
    filename,
    highlights,
    transcript_segments=None,
    mode=None,
):
    cfg = settings(mode)
    executable = ffmpeg_path()

    source = UPLOAD_DIR / filename

    if not source.is_file():
        raise FileNotFoundError(
            f"Uploaded video not found: {filename}"
        )

    if not highlights:
        raise ValueError(
            "No highlights available."
        )

    selected_highlights = highlights[:cfg["limit"]]

    print(
        f"Selected highlights: {len(highlights)}"
    )

    print(
        f"Rendering up to {len(selected_highlights)} "
        f"Shorts in {cfg['mode']} mode."
    )

    results = []

    for index, highlight in enumerate(
        selected_highlights,
        start=1,
    ):
        start = float(highlight["start"])
        end = float(highlight["end"])

        if not all(
            math.isfinite(value)
            for value in (start, end)
        ):
            raise ValueError(
                f"Invalid timestamps in Short {index}."
            )

        if start < 0 or end <= start:
            raise ValueError(
                f"Invalid duration in Short {index}."
            )

        end = min(
            end,
            start + cfg["seconds"],
        )

        duration = end - start

        stem = Path(filename).stem

        clip_name = (
            f"{stem}_clip_{index}_{cfg['mode']}.mp4"
        )

        caption_name = (
            f"{stem}_clip_{index}_{cfg['mode']}.ass"
        )

        output = CLIPS_DIR / clip_name
        caption_file = CAPTION_DIR / caption_name

        # ----------------------------------
        # GENERATE CAPTIONS
        # ----------------------------------

        has_captions, word_timed = create_captions(
            caption_file,
            transcript_segments,
            start,
            end,
            cfg["width"],
            cfg["height"],
        )

        # ----------------------------------
        # CONVERT VIDEO TO 9:16
        # ----------------------------------

        video_filter = (
            f"scale={cfg['width']}:{cfg['height']}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={cfg['width']}:{cfg['height']}:"
            "(ow-iw)/2:(oh-ih)/2:black,"
            "setsar=1"
        )

        if has_captions:
            video_filter += (
                f",ass=clip_captions/{caption_name}"
            )

        video_filter += ",format=yuv420p"

        # Temporary output prevents a failed
        # render from destroying the previous MP4.

        temporary = (
            CLIPS_DIR
            / f"{stem}_clip_{index}_pending.mp4"
        )

        command = [
            executable,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-ss", str(start),
            "-i", str(source),
            "-t", str(duration),
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-vf", video_filter,
            "-c:v", "libx264",
            "-preset", cfg["preset"],
            "-crf", str(cfg["crf"]),
            "-r", str(cfg["fps"]),
            "-c:a", "aac",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(temporary),
        ]

        print(
            f"Rendering Short {index}/"
            f"{len(selected_highlights)}: "
            f"{duration:.1f}s"
        )

        started = time.perf_counter()

        try:
            execute(command)

            if (
                not temporary.is_file()
                or temporary.stat().st_size < 1024
            ):
                raise RuntimeError(
                    "FFmpeg did not produce a "
                    "valid-sized MP4."
                )

            temporary.replace(output)

        finally:
            temporary.unlink(missing_ok=True)

        elapsed = time.perf_counter() - started

        results.append({
            "title": highlight.get(
                "title",
                f"Short {index}",
            ),
            "filename": clip_name,
            "video_url": (
                f"/clips/{clip_name}"
                f"?v={time.time_ns()}"
            ),
            "start": start,
            "end": end,
            "captions_added": has_captions,
            "word_timed_captions": word_timed,
            "render_mode": cfg["mode"],
            "render_seconds": round(elapsed, 2),
            "resolution": (
                f"{cfg['width']}x{cfg['height']}"
            ),
            "reframing": "full_frame",
        })

        print(
            f"Short {index} saved successfully "
            f"in {elapsed:.1f}s"
        )

    print(
        f"TOTAL SHORTS GENERATED: {len(results)}"
    )

    return results


# ==========================================
# 7. COMBINE GENERATED SHORTS
# ==========================================

def combine_shorts(filename, clips, mode):
    """
    Combine generated Shorts into one MP4.
    Individual Shorts remain unchanged.
    """

    if not clips:
        raise ValueError(
            "No clips available to combine."
        )

    executable = ffmpeg_path()
    stem = Path(filename).stem

    paths = [
        CLIPS_DIR / clip["filename"]
        for clip in clips
    ]

    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(
                f"Clip not found: {path.name}"
            )

    combined_name = (
        f"{stem}_combined_{mode}.mp4"
    )

    final_path = CLIPS_DIR / combined_name

    if len(paths) == 1:
        shutil.copyfile(
            paths[0],
            final_path,
        )

    else:
        with tempfile.TemporaryDirectory(
            prefix="concat_",
            dir=CLIPS_DIR,
        ) as temp_directory:

            temp_dir = Path(temp_directory)

            list_path = temp_dir / "files.txt"
            pending = temp_dir / "combined.mp4"

            list_path.write_text(
                "".join(
                    f"file '{path.as_posix()}'\n"
                    for path in paths
                ),
                encoding="utf-8",
            )

            base = [
                executable,
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_path),
            ]

            try:
                # First attempt: fast stream copying.

                execute(
                    base + [
                        "-c", "copy",
                        "-movflags", "+faststart",
                        str(pending),
                    ]
                )

            except RuntimeError:
                # Fallback: re-encode if needed.

                execute(
                    base + [
                        "-c:v", "libx264",
                        "-preset", "veryfast",
                        "-crf", "24",
                        "-c:a", "aac",
                        "-b:a", "128k",
                        "-movflags", "+faststart",
                        str(pending),
                    ]
                )

            pending.replace(final_path)

    print(
        f"Combined {len(paths)} Shorts successfully."
    )

    return {
        "filename": combined_name,
        "video_url": (
            f"/clips/{combined_name}"
            f"?v={time.time_ns()}"
        ),
        "clips_combined": len(paths),
    }
