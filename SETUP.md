# AI Video Editing Agent repair — 29 October 2026

This package contains only replacement/new source files, the regression test, and these instructions. It contains no `.env`, credentials, media, models, cached transcripts, or old source backups.

The repaired files are already installed in `D:\INDUSTRY_2026_SOURCE`. Original source files and the existing transcript/highlight/subtitle-review JSON files were backed up to `D:\INDUSTRY_2026_SOURCE\_repair_backup_20261029_27d23bc8`. The original media and `.env` were not accessed for installation.

## Run in the existing project

The existing interpreter `D:\.venv\Scripts\python.exe` was verified as Python 3.13.14 and can import Whisper. Use its full path; the generic `python` command points to an inaccessible Windows Store alias in the repair runner.

Stop the old backend with Ctrl+C in its terminal, then run in PowerShell:

```powershell
Set-Location 'D:\INDUSTRY_2026_SOURCE'
& 'D:\.venv\Scripts\python.exe' -m pip install -r .\requirements.txt
$env:WHISPER_MODEL = 'medium'
$env:TRANSCRIPTION_PROVIDER = 'auto'
$env:GEMINI_MODEL = 'gemini-3.1-flash-lite'
$env:SUBTITLE_AI_MODEL = 'gemini-3.1-flash-lite'
& 'D:\.venv\Scripts\python.exe' -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/dashboard and refresh the page fully. FFmpeg and ffprobe must remain on PATH; both were available during verification. The server normally reads the existing local `.env` when **you** start it. Keep the key there; do not paste it into chat. The repair process and all verification runs disabled `.env` loading and did not use a real API key. Shell settings above take precedence over older `.env` values.

If you received the ZIP on another machine rather than the repaired local project, first back up the five existing files listed below, then copy the ZIP contents into the project while preserving the `frontend` directory. Do not replace your uploads, transcripts, highlights, clips, subtitle_reviews, or `.env` directories/files.

## First demonstration

1. Upload the video. Choose **Hindi / Hinglish** for the supplied sample or **Auto detect** for mixed inputs.
2. Click **Find Best Clips** with fresh results enabled. Old unversioned highlight files are deliberately rejected. Long videos request 3–6 highlights; very short videos can return fewer.
3. Open **Edit / AI Correct Subtitles** for each highlight. This transcribes only selected intervals; a full-video transcript is optional and slower.
4. Preview captions. Use **AI Correct from Audio** or edit text and times manually. Add/delete captions as needed, then save.
5. Click **Generate MP4 Shorts + Captions**. Rendering uses the saved reviewed phrases and timings.

**Re-transcribe from Audio** listens again to that clip and backs up its previous saved draft. It preserves other clips' edits. A fresh full transcript invalidates all dependent drafts; old drafts are backed up when rebuilt. Close and reopen an editor if another operation refreshed its underlying transcript. The server rejects saves from an outdated editor instead of overwriting newer work.

If Gemini fails or no key is configured, transcription falls back to multilingual Whisper. `medium` is slower on CPU but gave better output than `small` on the supplied sample. Local transliteration is approximate and explicitly marked for review. If both speech engines fail, the subtitle editor still accepts manual captions. Save a reviewed draft for each clip before rendering in that case; an empty saved draft intentionally removes captions from that clip.

## Exact checks

Offline regression suite (no key, no model download, synthetic video; `.env` disabled inside the test):

```powershell
Set-Location 'D:\INDUSTRY_2026_SOURCE'
& 'D:\.venv\Scripts\python.exe' -m unittest -v test_repairs
& 'D:\.venv\Scripts\python.exe' -m compileall -q main.py video_editor.py gemini_analyzer.py transcription_service.py test_ai_transcription.py test_repairs.py
```

Local Hindi sample, without `.env` or an API request:

```powershell
$env:WHISPER_MODEL = 'medium'
& 'D:\.venv\Scripts\python.exe' .\test_ai_transcription.py .\uploads\0b6e3c5e52f89a50ab9efa6174fd33c2.mp4 --start 0 --seconds 21 --language hi --provider whisper --no-env
```

Optional **live Gemini check**, to be run by you using your locally configured key. This sends the selected audio interval to Gemini and can consume quota. It does not change transcript caches or saved edits:

```powershell
& 'D:\.venv\Scripts\python.exe' .\test_ai_transcription.py .\uploads\0b6e3c5e52f89a50ab9efa6174fd33c2.mp4 --start 0 --seconds 21 --language hi --provider gemini
```

The test also accepts any MP4 path, or no filename to choose the newest uploaded MP4. It no longer embeds the misspelled hash from the original test.

## Files and diagnosis

| File | Change |
| --- | --- |
| `gemini_analyzer.py` | New: restores `MODEL_NAME`, `get_video_duration(video_path)`, `analyze_video(video_path, context)`. Bounded upload processing, structured highlights, timestamp/overlap checks, remote upload cleanup. |
| `transcription_service.py` | New: audio-based Gemini Romanized transcription in bounded chunks; validates Latin text and times; multilingual Whisper fallback, Urdu-detection retry, repetition filtering, explicit review warnings. |
| `main.py` | Integrates transcription, versioned caches and source/settings checks, atomic JSON saves, backup/rebuild behavior, manual caption additions/deletions, outdated-editor protection, real audio reset and correction. |
| `video_editor.py` | Fixes Unicode normalization and preserves reviewed caption phrases/times. Keeps the existing FFmpeg render settings, 60-second cap, six-clip limit, and compilation. |
| `frontend/index.html` | Adds language and fresh-result controls, fallback notices, caption add/delete actions and revision handling. |
| `requirements.txt` | Pins the tested direct runtime dependencies and test-client dependencies. |
| `test_ai_transcription.py` | Replaces the hard-coded filename with an explicit CLI; importing it no longer triggers API work. |
| `test_repairs.py` | Offline HTTP, cache, correction, fallback, editing and real FFmpeg regression checks. |

The three active uploaded source files matched `D:\INDUSTRY_2026_SOURCE` byte for byte. The original full transcript had 200 Urdu-script segments out of 295; the selected transcript had 25 out of 33 and a punctuation-only segment. Both Romanization functions used double-escaped Unicode ranges, so they did not match the intended scripts. The backend forced `language="hi"` even for English and defaulted to an English-only Whisper model. Cached transcripts were relabeled Romanized without fixing recognition; subtitle reset reused that cache. Transliteration alone cannot correct misheard speech.

## Verification and limits

18 regression tests passed in the project's existing Python environment. They covered upload, health, dashboard, transcription, highlight selection/editing, subtitle GET/save/reset/correction, process, render, combine and output-serving routes. AI responses were simulated to verify validation, cleanup and failures. Actual FFmpeg rendered six 360×640 fast Shorts, three 720×1280 quality Shorts and a six-clip compilation; durations and manual caption timings were checked. Python imports and compilation and dashboard JavaScript syntax passed.

A real, offline 21-second test used the supplied video and the already cached medium model. It produced eight Latin-script segments, retaining the spoken English phrase at the end. This confirms local processing and script conversion, **not** perfect Hindi spelling or full-video accuracy. The small-model trial repeated a phrase; the final code adds repetition controls and uses medium by default. No real Gemini request was made, so live model access, quota, recognition accuracy and timing still require the optional check above. AI phrase timing remains approximate and editable.

API integration references: [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/), [Gemini 3.1 Flash-Lite model and audio input](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
