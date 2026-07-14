import datetime
import json
import math
import os
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path

def _load_service(relative_path, initial_globals=None):
    module = types.ModuleType(f"test_{Path(relative_path).stem}")
    module.__dict__.update(initial_globals or {})
    path = Path(__file__).parents[1] / relative_path
    exec(compile(path.read_text(encoding="utf-8-sig"), str(path), "exec"), module.__dict__)
    return module


subtitle_service = _load_service(
    "app/core/subtitle_service.py",
    {"DEFAULT_SUBTITLE_LANGUAGE": "zh-CN"},
)
youtube_service = _load_service("app/core/youtube_service.py")


class SubtitleTimingTests(unittest.TestCase):
    def setUp(self):
        self.subtitle_originals = {
            name: getattr(subtitle_service, name, None)
            for name in (
                "Path", "json", "datetime", "math", "os", "_subtitle_language_meta",
                "_subtitle_size_config", "_watermark_enabled", "_watermark_burns_with_subtitles",
                "_normalize_translator_label",
            )
        }
        subtitle_service.Path = Path
        subtitle_service.json = json
        subtitle_service.datetime = datetime
        subtitle_service.math = math
        subtitle_service.os = os
        subtitle_service._subtitle_language_meta = lambda value: ("zh-CN", {"label": "中文", "suffix": "zh"})
        subtitle_service._subtitle_size_config = lambda value: (
            value or "large",
            {"standard": {"scale": 1.0}, "large": {"scale": 1.16}, "douyin": {"scale": 1.48}}.get(
                value or "large",
                {"scale": 1.16},
            ),
        )
        subtitle_service._watermark_enabled = lambda job: False
        subtitle_service._watermark_burns_with_subtitles = lambda job: False
        subtitle_service._normalize_translator_label = lambda value: value or "Vidferry翻译"

    def tearDown(self):
        for name, value in self.subtitle_originals.items():
            if value is None:
                delattr(subtitle_service, name)
            else:
                setattr(subtitle_service, name, value)

    def test_transcribe_requests_word_timestamps_and_keeps_valid_words(self):
        captured = {}

        class FakeModel:
            def __init__(self, *args, **kwargs):
                pass

            def transcribe(self, path, **kwargs):
                captured.update(kwargs)
                segment = types.SimpleNamespace(
                    text=" This subway is fast.",
                    start=1.0,
                    end=2.1,
                    words=[
                        types.SimpleNamespace(word=" This", start=1.0, end=1.2, probability=0.99),
                        types.SimpleNamespace(word=" subway", start=1.25, end=1.6, probability=0.98),
                    ],
                )
                return [segment], types.SimpleNamespace(language="en")

        original_module = sys.modules.get("faster_whisper")
        sys.modules["faster_whisper"] = types.SimpleNamespace(WhisperModel=FakeModel)
        try:
            segments, language = subtitle_service._transcribe_audio("sample.wav")
        finally:
            if original_module is None:
                del sys.modules["faster_whisper"]
            else:
                sys.modules["faster_whisper"] = original_module

        self.assertTrue(captured["word_timestamps"])
        self.assertEqual(language, "en")
        self.assertEqual(segments[0]["words"][0]["word"], "This")
        self.assertAlmostEqual(segments[0]["words"][1]["end"], 1.6)

    def test_short_phrase_cues_respect_boundaries_and_invalid_words_fall_back(self):
        segment = {
            "start": 0,
            "end": 6,
            "text": "This subway is very clean and surprisingly fast today.",
            "words": [
                {"word": "This", "start": 0.0, "end": 0.3},
                {"word": "subway", "start": 0.35, "end": 0.8},
                {"word": "is", "start": 0.85, "end": 1.0},
                {"word": "very", "start": 1.05, "end": 1.4},
                {"word": "clean", "start": 1.45, "end": 1.8},
                {"word": "and", "start": 2.35, "end": 2.55},
                {"word": "surprisingly", "start": 2.6, "end": 3.1},
                {"word": "fast", "start": 3.15, "end": 3.45},
                {"word": "today.", "start": 3.5, "end": 3.9},
            ],
        }
        cues = subtitle_service._build_subtitle_cues([segment], "en")

        self.assertGreaterEqual(len(cues), 2)
        self.assertTrue(all(cue["end"] >= cue["start"] + 0.5 for cue in cues))
        self.assertTrue(all(left["end"] <= right["start"] for left, right in zip(cues, cues[1:])))
        self.assertTrue(all(cue["sourceSegmentIndex"] == 0 for cue in cues))

        long_cues = subtitle_service._build_subtitle_cues([{
            "start": 0,
            "end": 7,
            "text": "one two three four five six seven eight nine ten eleven twelve",
            "words": [
                {"word": str(index), "start": index * 0.48, "end": index * 0.48 + 0.25}
                for index in range(12)
            ],
        }], "en")
        self.assertTrue(all(cue["end"] - cue["start"] <= 5 for cue in long_cues))

        fallback = subtitle_service._build_subtitle_cues([{
            "start": 4,
            "end": 6,
            "text": "Broken timestamp cache.",
            "words": [{"word": "Broken", "start": 5, "end": 4.5}],
        }], "en")
        self.assertEqual(fallback[0]["text"], "Broken timestamp cache.")
        self.assertEqual(fallback[0]["words"], [])

    def test_translation_allocation_preserves_all_characters_and_rejects_too_short_text(self):
        cues = [
            {"text": "This subway is very clean"},
            {"text": "and it is also fast today"},
        ]
        translation = "这条地铁很干净，而且今天速度也很快。"
        allocated = subtitle_service._allocate_translated_cues(cues, translation)

        self.assertEqual("".join(allocated), translation)
        self.assertTrue(all(item for item in allocated))
        self.assertIsNone(subtitle_service._allocate_translated_cues(cues, "好"))

        rendered = subtitle_service._assign_translated_cues(
            [{"start": 0, "end": 2, "text": "This is a cue", "sourceSegmentIndex": 0, "words": []}, {
                "start": 2, "end": 4, "text": "And this is another cue", "sourceSegmentIndex": 0, "words": [],
            }],
            [{"start": 0, "end": 4, "text": "This is a full sentence", "subtitle": "好"}],
            "en",
        )
        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0]["subtitle"], "好")

    def test_translated_chinese_profanity_is_masked_without_changing_source_text(self):
        translated = subtitle_service._redact_generated_subtitles([{
            "start": 0,
            "end": 4,
            "text": "This is fucking terrible.",
            "subtitle": "这也太他妈的糟糕了。",
        }], "zh-CN")
        rendered = subtitle_service._assign_translated_cues(
            [{
                "start": 0,
                "end": 4,
                "text": "This is fucking terrible.",
                "sourceSegmentIndex": 0,
                "words": [],
            }],
            translated,
            "en",
        )

        self.assertEqual(rendered[0]["text"], "This is fucking terrible.")
        self.assertEqual(rendered[0]["subtitle"], "这也太*糟糕了。")
        other_language = [{"subtitle": "这也太他妈的糟糕了。"}]
        self.assertIs(subtitle_service._redact_generated_subtitles(other_language, "ja"), other_language)
        self.assertEqual(other_language[0]["subtitle"], "这也太他妈的糟糕了。")

    def test_chinese_overflow_is_split_in_its_original_time_range_without_font_override(self):
        video_info = {"width": 1080, "height": 1920}
        self.assertEqual(
            subtitle_service._subtitle_render_layout({"subtitleSize": "large"}, video_info)["singleLineCapacity"],
            9,
        )
        self.assertGreater(
            subtitle_service._subtitle_render_layout({"subtitleSize": "standard"}, video_info)["singleLineCapacity"],
            subtitle_service._subtitle_render_layout({"subtitleSize": "douyin"}, video_info)["singleLineCapacity"],
        )

        cue = {
            "start": 1,
            "end": 3,
            "text": "This subway is very clean and very fast.",
            "sourceSegmentIndex": 0,
            "words": [],
        }
        translation = "这条地铁很干净，而且速度非常快。"
        rendered = subtitle_service._assign_translated_cues(
            [cue],
            [{"subtitle": translation}],
            "en",
            max_single_line_chars=8,
        )

        self.assertGreater(len(rendered), 1)
        self.assertEqual("".join(item["subtitle"] for item in rendered), translation)
        self.assertEqual(rendered[0]["start"], 1)
        self.assertEqual(rendered[-1]["end"], 3)
        self.assertTrue(all(subtitle_service._visible_text_length(item["subtitle"]) <= 8 for item in rendered))
        self.assertTrue(all(left["end"] <= right["start"] for left, right in zip(rendered, rendered[1:])))
        self.assertEqual(rendered[0]["text"], cue["text"])
        self.assertTrue(all(not item["text"] for item in rendered[1:]))

        with tempfile.TemporaryDirectory() as tmp_dir:
            ass_file = Path(tmp_dir) / "subtitle.ass"
            subtitle_service._build_ass_file(
                {"subtitleLanguage": "zh-CN", "subtitleSize": "large"},
                rendered,
                ass_file,
                5,
                video_info,
            )
            lines = ass_file.read_text(encoding="utf-8").splitlines()

        subtitle_lines = [line for line in lines if ",Subtitle," in line]
        self.assertEqual(len(subtitle_lines), len(rendered))
        self.assertTrue(all(r"\N" not in line for line in subtitle_lines))
        self.assertTrue(all(r"{\fs" not in line for line in subtitle_lines))

    def test_chinese_split_prefers_punctuation_and_handles_insufficient_words(self):
        self.assertEqual(
            subtitle_service._split_translated_subtitle("这是第一句，第二句内容", 7),
            ["这是第一句，", "第二句内容"],
        )
        self.assertEqual(
            subtitle_service._split_translated_subtitle("一二三四五六七八九十", 4),
            ["一二三四", "五六七八", "九十"],
        )

        rendered = subtitle_service._assign_translated_cues(
            [{
                "start": 0,
                "end": 3,
                "text": "one two",
                "sourceSegmentIndex": 0,
                "words": [
                    {"word": "one", "start": 0, "end": 1},
                    {"word": "two", "start": 1, "end": 2},
                ],
            }],
            [{"subtitle": "一二三四五六七八"}],
            "en",
            max_single_line_chars=3,
        )
        self.assertEqual([item["text"] for item in rendered], ["one", "two", ""])
        self.assertEqual("".join(item["subtitle"] for item in rendered), "一二三四五六七八")

    def test_new_transcript_payload_is_versioned(self):
        originals = {
            name: getattr(subtitle_service, name, None)
            for name in (
                "_get_youtube_video_record", "_transcript_path", "_extract_audio_for_whisper",
                "_transcribe_audio", "_update_translate_progress", "update_youtube_video_artifacts",
            )
        }
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                transcript_file = Path(tmp_dir) / "sample.json"
                subtitle_service._get_youtube_video_record = lambda video_id: None
                subtitle_service._transcript_path = lambda video_id, source: transcript_file
                subtitle_service._extract_audio_for_whisper = lambda source, work: Path(work) / "audio.wav"
                subtitle_service._transcribe_audio = lambda audio: ([{
                    "start": 0,
                    "end": 1,
                    "text": "Hello",
                    "words": [{"word": "Hello", "start": 0, "end": 1, "probability": 0.9}],
                }], "en")
                subtitle_service._update_translate_progress = lambda *args, **kwargs: None
                subtitle_service.update_youtube_video_artifacts = lambda *args, **kwargs: None

                subtitle_service._get_or_create_transcript(
                    {"id": "job", "videoId": "video"},
                    "source.mp4",
                    Path(tmp_dir),
                )
                payload = json.loads(transcript_file.read_text(encoding="utf-8"))
        finally:
            for name, value in originals.items():
                if value is None:
                    delattr(subtitle_service, name)
                else:
                    setattr(subtitle_service, name, value)

        self.assertEqual(payload["schemaVersion"], 2)
        self.assertEqual(payload["segments"][0]["words"][0]["word"], "Hello")


class TranscriptResetTests(unittest.TestCase):
    def test_transcript_cache_helper_deletes_only_video_cache(self):
        originals = {name: getattr(youtube_service, name, None) for name in ("Path", "re", "YOUTUBE_TRANSCRIPT_DIR")}
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                transcript_dir = Path(tmp_dir)
                target = transcript_dir / "video-id.json"
                other = transcript_dir / "other.json"
                target.write_text("{}", encoding="utf-8")
                other.write_text("{}", encoding="utf-8")
                youtube_service.Path = Path
                youtube_service.re = re
                youtube_service.YOUTUBE_TRANSCRIPT_DIR = transcript_dir

                deleted = youtube_service._delete_youtube_transcript_cache({"video_id": "video-id"})
                target_exists = target.exists()
                other_exists = other.exists()
        finally:
            for name, value in originals.items():
                if value is None:
                    delattr(youtube_service, name)
                else:
                    setattr(youtube_service, name, value)

        self.assertEqual(deleted, [str(target)])
        self.assertFalse(target_exists)
        self.assertTrue(other_exists)

    def test_reset_with_refresh_clears_transcript_references_without_deleting_source(self):
        originals = {
            name: getattr(youtube_service, name, None)
            for name in (
                "init_youtube_workflow_table", "_db_connect", "sqlite3", "_assert_no_active_youtube_job",
                "_delete_youtube_transcript_cache", "_sync_youtube_processed_state", "_row_to_youtube_video",
            )
        }
        executed = []

        class Cursor:
            def execute(self, statement, values=()):
                executed.append((statement, values))

            def fetchone(self):
                return {"video_id": "video-id"}

            def fetchall(self):
                return []

        class Connection:
            row_factory = None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def cursor(self):
                return Cursor()

            def commit(self):
                pass

        try:
            youtube_service.init_youtube_workflow_table = lambda: None
            youtube_service._db_connect = lambda: Connection()
            youtube_service.sqlite3 = types.SimpleNamespace(Row=object)
            youtube_service._assert_no_active_youtube_job = lambda cursor, video_id: None
            youtube_service._delete_youtube_transcript_cache = lambda video: ["video-id.json"]
            youtube_service._sync_youtube_processed_state = lambda cursor, video_id: {}
            youtube_service._row_to_youtube_video = lambda row: {"id": row["video_id"]}

            result = youtube_service.reset_youtube_video_processing(
                "video-id",
                delete_processed=False,
                refresh_transcript=True,
            )
        finally:
            for name, value in originals.items():
                if value is None:
                    delattr(youtube_service, name)
                else:
                    setattr(youtube_service, name, value)

        statements = "\n".join(statement for statement, _ in executed)
        self.assertTrue(result["transcriptRefreshed"])
        self.assertEqual(result["deletedTranscriptFiles"], ["video-id.json"])
        self.assertIn("SET transcript_status = 0", statements)
        self.assertNotIn("downloaded_file_path", statements)


if __name__ == "__main__":
    unittest.main()
