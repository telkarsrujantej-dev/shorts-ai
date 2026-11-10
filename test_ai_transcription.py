"""Explicit audio smoke test; importing this file performs no work."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Test a real audio interval without changing cached transcripts.")
    parser.add_argument("video", nargs="?", help="MP4 path or name inside uploads; otherwise newest upload")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--seconds", type=float, default=21)
    parser.add_argument("--language", choices=("auto", "hi", "en"), default="auto")
    parser.add_argument("--provider", choices=("auto", "gemini", "whisper"), default="auto")
    parser.add_argument("--no-env", action="store_true", help="Never read .env")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if not args.no_env and os.getenv("AI_VIDEO_AGENT_LOAD_ENV", "1") != "0":
        from dotenv import load_dotenv
        load_dotenv(root / ".env", override=False)
    from gemini_analyzer import get_video_duration
    from transcription_service import transcribe_ranges
    if args.video:
        video = Path(args.video)
        if not video.is_file():
            video = root / "uploads" / args.video
    else:
        videos = list((root / "uploads").glob("*.mp4"))
        if not videos:
            parser.error("No MP4 found. Pass a video path or upload one first.")
        video = max(videos, key=lambda p: p.stat().st_mtime_ns)
    duration = get_video_duration(video)
    end = min(duration, args.start + args.seconds)
    if not 0 <= args.start < end or args.seconds <= 0:
        parser.error("Choose a positive interval inside the video.")
    result = transcribe_ranges(video, [(args.start, end)], language=args.language, provider=args.provider)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("No cached transcripts, subtitle edits or rendered clips were changed.")


if __name__ == "__main__":
    main()
