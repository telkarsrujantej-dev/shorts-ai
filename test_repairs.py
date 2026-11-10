"""Offline regression checks: real HTTP routing and FFmpeg, simulated AI responses.

Run: python -m unittest -v test_repairs
Never reads .env, sends media to a service, or downloads a speech model.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ["AI_VIDEO_AGENT_LOAD_ENV"] = "0"

from fastapi.testclient import TestClient
import main
import gemini_analyzer as ga
import transcription_service as speech
import video_editor as editor


def fake_transcript(video, ranges, language="auto", **kwargs):
    segments = []
    for start, end in ranges:
        end = end if end is not None else 12
        segments.append({"start": start + .1, "end": min(end, start + 1.8),
                         "text": "Yeh test caption hai", "words": []})
    return {"segments": segments, "language": language, "sources": ["test"], "warnings": []}


class RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise unittest.SkipTest("FFmpeg and ffprobe are required for these checks")
        cls.master = tempfile.TemporaryDirectory(prefix="repair_checks_", dir=Path(__file__).parent)
        cls.fixture = Path(cls.master.name) / "source.mp4"
        subprocess.run([shutil.which("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=navy:s=320x180:r=20:d=12",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                        "-shortest", str(cls.fixture)], check=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        cls.master.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.master.name)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ("uploads", "transcripts", "highlights", "clips", "clip_captions", "subtitle_reviews"):
            (self.root / folder).mkdir()
        mapping = {"BASE_DIR": self.root, "UPLOADS": self.root / "uploads", "TRANSCRIPTS": self.root / "transcripts",
                   "HIGHLIGHTS": self.root / "highlights", "CLIPS": self.root / "clips",
                   "SUBTITLE_REVIEWS": self.root / "subtitle_reviews"}
        self.begin_patch(patch.multiple(main, **mapping))
        self.begin_patch(patch.multiple(editor, BASE_DIR=self.root, UPLOAD_DIR=mapping["UPLOADS"],
                                       CLIPS_DIR=mapping["CLIPS"], CAPTION_DIR=self.root / "clip_captions"))
        self.begin_patch(patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": "",
                                               "TRANSCRIPTION_PROVIDER": "auto", "AI_VIDEO_AGENT_LOAD_ENV": "0"}))
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        response = self.client.post("/upload", files={"file": ("sample.mp4", self.fixture.read_bytes(), "video/mp4")})
        self.assertEqual(response.status_code, 200, response.text)
        self.filename = response.json()["filename"]
        self.selected = [{"start": i * 2, "end": (i + 1) * 2, "title": f"Clip {i + 1}", "reason": "Fixture", "score": 8}
                         for i in range(6)]
        self.transcriber = self.begin_patch(patch.object(main, "transcribe_ranges", side_effect=fake_transcript))
        self.analyzer = self.begin_patch(patch.object(main, "analyze_video", return_value=self.selected))
        self.assertEqual(self.client.post(f"/highlights/{self.filename}").status_code, 200)

    def begin_patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def draft(self, index=0):
        response = self.client.get(f"/subtitle-review/{self.filename}/{index}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def save(self, doc, cues, index=0):
        return self.client.put(f"/subtitle-review/{self.filename}/{index}",
                                json={"revision": doc["revision"], "mode": "romanized", "cues": cues})

    def test_core_routes_and_upload_validation(self):
        for path in ("/", "/health", "/dashboard", "/openapi.json", f"/videos/{self.filename}"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.post("/upload", files={"file": ("x.txt", b"x")}).status_code, 400)
        self.assertEqual(self.client.post("/upload", files={"file": ("x.mp4", b"")}).status_code, 400)
        self.assertEqual(self.client.post("/transcribe/bad.mp4").status_code, 400)
        self.assertEqual(self.client.get("/clips/bad.mp4").status_code, 400)
        self.assertEqual(self.client.post(f"/transcribe/{self.filename}?language=invalid").status_code, 422)
        self.assertIn("no-store", self.client.get("/dashboard").headers["cache-control"])

    def test_legacy_and_forced_transcript_cache(self):
        path = main.json_path(main.TRANSCRIPTS, self.filename)
        path.write_text(json.dumps({"filename": self.filename, "segments": [{"text": "اردو"}]}), encoding="utf-8")
        first = self.client.post(f"/transcribe/{self.filename}").json()
        self.assertFalse(first["cached"])
        self.assertTrue(self.client.post(f"/transcribe/{self.filename}").json()["cached"])
        fresh = self.client.post(f"/transcribe/{self.filename}?force=true").json()
        self.assertFalse(fresh["cached"])
        self.assertNotEqual(first["revision"], fresh["revision"])
        self.assertTrue(list(path.parent.glob("*.backup.json")))
        self.assertEqual(self.transcriber.call_count, 2)

    def test_settings_and_source_change_invalidate_cache(self):
        first = main.get_full_transcript(self.filename)
        hindi = main.get_full_transcript(self.filename, language="hi")
        self.assertNotEqual(first["revision"], hindi["revision"])
        path = main.validate_video(self.filename)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
        self.assertIsNone(main.load_cached(main.json_path(main.TRANSCRIPTS, self.filename), self.filename, "segments"))

    def test_manual_add_delete_and_stale_save(self):
        doc = self.draft()
        cues = [{"id": 0, "start": .2, "end": .8, "text": "Matter chhote particles se bana hai"},
                {"id": 1, "start": 1, "end": 1.9, "text": "English stays English"}]
        saved = self.save(doc, cues)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.save(doc, cues).status_code, 409)
        transcript = main.get_selected_transcript(self.filename, self.selected)
        merged = main.merge_reviewed_subtitles(self.filename, self.selected, transcript)
        events, _ = editor.caption_events(merged, 0, 2)
        self.assertEqual(events, [(.2, .8, cues[0]["text"]), (1, 1.9, cues[1]["text"])])
        self.assertEqual(self.save(saved.json(), []).status_code, 200)
        merged = main.merge_reviewed_subtitles(self.filename, self.selected, transcript)
        self.assertEqual(editor.caption_events(merged, 0, 2)[0], [])
        self.assertTrue(editor.caption_events(merged, 2, 4)[0])

    def test_invalid_manual_timing_and_script(self):
        doc = self.draft()
        for cues in ([{"id": 0, "start": 0, "end": 3, "text": "Hello"}],
                     [{"id": 0, "start": 0, "end": 1, "text": "हिंदी"}],
                     [{"id": 0, "start": 0, "end": 1.5, "text": "Hello"},
                      {"id": 1, "start": 1, "end": 2, "text": "World"}]):
            self.assertEqual(self.save(doc, cues).status_code, 400)

    def test_force_invalidates_review_and_backs_up(self):
        doc = self.draft()
        saved = self.save(doc, [{"id": 0, "start": .1, "end": 1, "text": "Manual correction"}]).json()
        main.get_full_transcript(self.filename, force=True)
        renewed = self.draft()
        self.assertNotEqual(renewed["transcript_revision"], saved["transcript_revision"])
        self.assertNotEqual(renewed["cues"][0]["text"], "Manual correction")
        self.assertTrue(list(main.SUBTITLE_REVIEWS.glob("*.backup.json")))

    def test_reset_retranscribes_only_target_without_destroying_other_edit(self):
        first, other = self.draft(), self.draft(1)
        saved = self.save(other, [{"id": 0, "start": .1, "end": 1, "text": "Keep this edit"}], 1).json()
        count = self.transcriber.call_count
        response = self.client.post(f"/subtitle-review/{self.filename}/0/reset")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.transcriber.call_count, count + 1)
        self.assertEqual(self.transcriber.call_args.args[1], [(0.0, 2.0)])
        self.assertEqual(self.draft(1)["revision"], saved["revision"])
        self.assertNotEqual(response.json()["revision"], first["revision"])

    def test_ai_correction_success_and_failure_preserve_timings(self):
        doc = self.draft()
        client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **k: SimpleNamespace(
            text=json.dumps({"cues": [{"id": c["id"], "text": "Sahi Romanized Hindi"} for c in doc["cues"]]}))), close=lambda: None)
        url = f"/subtitle-review/{self.filename}/0/ai"
        with patch.object(main, "make_client", return_value=client):
            response = self.client.post(url, json={"mode": "auto", "revision": doc["revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        fixed = response.json()
        self.assertEqual([(c["start"], c["end"]) for c in fixed["cues"]], [(c["start"], c["end"]) for c in doc["cues"]])
        client.models.generate_content = lambda **k: SimpleNamespace(text='{"cues":[{"id":0,"text":"اردو"}]}')
        with patch.object(main, "make_client", return_value=client):
            failed = self.client.post(url, json={"mode": "auto", "revision": fixed["revision"]})
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(self.draft()["revision"], fixed["revision"])

    def test_highlight_edit_validation_and_new_draft(self):
        doc = self.draft()
        url = f"/update-highlight/{self.filename}/0"
        self.assertEqual(self.client.post(url, json={"start": 0, "end": 3}).status_code, 400)
        self.assertEqual(self.client.post(url, json={"start": .3, "end": 1.9}).status_code, 200)
        self.assertEqual(self.draft()["video_start"], .3)
        self.assertNotEqual(self.draft()["revision"], doc["revision"])

    def test_actual_six_fast_three_quality_and_combination(self):
        doc = self.draft()
        self.save(doc, [{"id": 0, "start": .1, "end": 1.8, "text": "Manual caption stays in sync"}])
        response = self.client.post(f"/generate-clips/{self.filename}?mode=fast")
        self.assertEqual(response.status_code, 200, response.text)
        clips = response.json()["clips"]
        self.assertEqual(len(clips), 6)
        for clip in clips:
            self.assertTrue(clip["captions_added"])
            self.assertAlmostEqual(ga.get_video_duration(main.CLIPS / clip["filename"]), 2, delta=.2)
            probe = json.loads(subprocess.check_output([shutil.which("ffprobe"), "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "json", str(main.CLIPS / clip["filename"])], text=True))
            self.assertEqual((probe["streams"][0]["width"], probe["streams"][0]["height"]), (360, 640))
            self.assertEqual(self.client.get(clip["video_url"]).status_code, 200)
        ass = next((self.root / "clip_captions").glob("*clip_1_fast.ass")).read_text(encoding="utf-8")
        self.assertIn("0:00:00.10,0:00:01.80", ass)
        combined = self.client.post(f"/combine-clips/{self.filename}?mode=fast")
        self.assertEqual(combined.status_code, 200, combined.text)
        self.assertEqual(combined.json()["clips_combined"], 6)
        self.assertAlmostEqual(ga.get_video_duration(main.CLIPS / combined.json()["filename"]), 12, delta=.4)
        quality = editor.create_shorts(self.filename, self.selected[:3], fake_transcript(None, [(0, 6)])["segments"], "quality")
        self.assertEqual(len(quality), 3)
        self.assertTrue(all(c["resolution"] == "720x1280" for c in quality))

    def test_process_route_passes_language_and_force(self):
        with patch.object(main, "create_shorts", return_value=[]):
            response = self.client.post(f"/process/{self.filename}?language=hi&force_transcript=true")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.transcriber.call_args.kwargs["language"], "hi")

    def test_manual_editor_survives_unavailable_speech_engines(self):
        self.transcriber.side_effect = RuntimeError("Speech engine unavailable")
        doc = self.draft()
        self.assertEqual(doc["cues"], [])
        self.assertTrue(any("unavailable" in w for w in doc["warnings"]))
        self.assertEqual(self.client.post(f"/generate-clips/{self.filename}").status_code, 422)
        for index in range(6):
            doc = self.draft(index)
            response = self.save(doc, [{"id": 0, "start": .1, "end": 1.9, "text": "Manually entered caption"}], index)
            self.assertEqual(response.status_code, 200, response.text)
        with patch.object(main, "create_shorts", return_value=[]) as render:
            response = self.client.post(f"/generate-clips/{self.filename}")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(render.call_args.args[2]), 6)

    def test_missing_key_returns_clean_error(self):
        with patch.object(main, "analyze_video", ga.analyze_video):
            response = self.client.post(f"/highlights/{self.filename}?force=true")
        self.assertEqual(response.status_code, 502)
        doc = self.draft()
        response = self.client.post(f"/subtitle-review/{self.filename}/0/ai", json={"revision": doc["revision"], "mode": "auto"})
        self.assertEqual(response.status_code, 400)

    def test_audio_ai_fallback_and_absolute_offsets(self):
        local = [{"start": .1, "end": .9, "text": "Yeh English test hai", "words": []}]
        with patch.dict(os.environ, {"GEMINI_API_KEY": "offline-test-placeholder"}), \
                patch.object(speech, "ai_transcribe", side_effect=ValueError("bad schema")), \
                patch.object(speech, "whisper_transcribe", side_effect=lambda *a: ([dict(x) for x in local], "hi")):
            result = speech.transcribe_ranges(self.fixture, [(5, 7), (9, 11)])
        self.assertEqual([s["start"] for s in result["segments"]], [5.1, 9.1])
        self.assertEqual(result["sources"], ["whisper"])
        self.assertTrue(any("fallback" in x for x in result["warnings"]))

    def test_whisper_auto_english_and_urdu_retry(self):
        segment = SimpleNamespace(start=0, end=1, text="English stays English", words=[])
        model = SimpleNamespace(transcribe=lambda *a, **k: (iter([segment]), SimpleNamespace(language="en")))
        with patch.object(speech, "whisper", return_value=model), patch.object(model, "transcribe", wraps=model.transcribe) as call:
            result, language = speech.whisper_transcribe("test.wav", 2, "auto")
            self.assertIsNone(call.call_args.kwargs["language"])
            self.assertEqual(language, "en")
        with patch.object(speech, "whisper", return_value=model), patch.object(model, "transcribe", side_effect=[
                (iter([segment]), SimpleNamespace(language="ur")), (iter([segment]), SimpleNamespace(language="hi"))]) as call:
            speech.whisper_transcribe("test.wav", 2, "auto")
            self.assertEqual(call.call_args_list[1].kwargs["language"], "hi")

    def test_romanization_and_invalid_word_times(self):
        for text in ("यह Hindi English है", "یہ English ہے", "нیوترگہ"):
            normalized = speech.normalize_caption_text(text)
            self.assertTrue(normalized.isascii())
        self.assertEqual(speech.normalize_caption_text("English AI 2026"), "English AI 2026")
        self.assertFalse(speech.meaningful("۔ ۔ ۔ ۔"))
        self.assertFalse(speech.meaningful("ڈ" * 100))
        self.assertFalse(speech.meaningful("leks pridmeN " * 12))
        events, _ = editor.caption_events([{"start": 0, "end": 2, "text": "Readable caption",
                                           "words": [{"start": 1, "end": 1, "word": "bad"}]}], 0, 2)
        self.assertTrue(events)

    def test_ai_rejects_wrong_script_overlap_and_out_of_range(self):
        audio = self.root / "audio.wav"
        speech.extract_audio(self.fixture, audio, 0, 2)
        for segments in ([{"start": 0, "end": 1, "text": "اردو"}],
                         [{"start": 0, "end": 3, "text": "Hello"}],
                         [{"start": 0, "end": 1.5, "text": "Hello"}, {"start": 1, "end": 2, "text": "World"}]):
            client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **k: SimpleNamespace(
                text=json.dumps({"language": "hi", "segments": segments}))), close=lambda: None)
            with patch.object(speech, "make_client", return_value=client), self.assertRaises(ValueError):
                speech.ai_transcribe(audio, 2, "auto")

    def test_gemini_upload_lifecycle_cleanup_and_validation(self):
        uploaded = SimpleNamespace(name="files/offline-test", state=SimpleNamespace(name="ACTIVE"))
        client = SimpleNamespace(files=SimpleNamespace(upload=lambda **k: uploaded, delete=lambda **k: None),
                                 models=SimpleNamespace(generate_content=lambda **k: SimpleNamespace(
                                     text=json.dumps({"highlights": self.selected}))), close=lambda: None)
        with patch.object(ga, "make_client", return_value=client), patch.object(client.files, "delete", wraps=client.files.delete) as delete:
            self.assertEqual(len(ga.analyze_video(self.fixture, [])), 6)
            delete.assert_called_once_with(name="files/offline-test")
        bad = [dict(x) for x in self.selected]
        bad[0]["end"] = 80
        with self.assertRaises(ValueError):
            ga.validate_highlights(bad, 200)
        with self.assertRaises(ValueError):
            ga.validate_highlights(self.selected[:2], 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
