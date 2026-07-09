import tempfile
import unittest
from pathlib import Path

import app.core.editing_service as editing_service


def _format_ass_timestamp(seconds):
    seconds = max(0, float(seconds or 0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole_seconds = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


class EditingUpNextOverlayTests(unittest.TestCase):
    def setUp(self):
        self.original_path = getattr(editing_service, "Path", None)
        self.original_escape = getattr(editing_service, "_escape_ass_text", None)
        self.original_timestamp = getattr(editing_service, "_format_ass_timestamp", None)
        self.original_subtitle_path = getattr(editing_service, "_ffmpeg_subtitle_path", None)
        editing_service.Path = Path
        editing_service._escape_ass_text = lambda value: str(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        editing_service._format_ass_timestamp = _format_ass_timestamp
        editing_service._ffmpeg_subtitle_path = lambda path: Path(path).as_posix().replace(":", "\\:").replace("'", "\\'")

    def tearDown(self):
        if self.original_path is None:
            delattr(editing_service, "Path")
        else:
            editing_service.Path = self.original_path
        if self.original_escape is None:
            delattr(editing_service, "_escape_ass_text")
        else:
            editing_service._escape_ass_text = self.original_escape
        if self.original_timestamp is None:
            delattr(editing_service, "_format_ass_timestamp")
        else:
            editing_service._format_ass_timestamp = self.original_timestamp
        if self.original_subtitle_path is None:
            delattr(editing_service, "_ffmpeg_subtitle_path")
        else:
            editing_service._ffmpeg_subtitle_path = self.original_subtitle_path

    def test_up_next_ass_contains_neon_text_and_light_animation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ass_file = Path(tmp_dir) / "up_next.ass"
            editing_service._write_editing_up_next_overlay_ass(ass_file, 1080, 1920, 6)
            content = ass_file.read_text(encoding="utf-8")

        self.assertIn(editing_service.EDITING_UP_NEXT_TEXT, content)
        self.assertIn("Microsoft YaHei", content)
        self.assertIn("UpNextGlow", content)
        self.assertIn(r"\fscx106\fscy106", content)
        self.assertIn(r"\blur7", content)
        self.assertIn("&HFFE660&", content)

    def test_intro_filters_include_subtitles_without_background_box(self):
        filters = editing_service._editing_intro_video_filters(
            1080,
            1920,
            is_intro_clip=True,
            overlay_ass_file=Path("work") / "up_next.ass",
        )

        self.assertTrue(any(item.startswith("subtitles=") for item in filters))
        self.assertNotIn("drawbox=", ",".join(filters))
        self.assertNotIn("white@0.30", ",".join(filters))

    def test_main_filters_do_not_include_overlay(self):
        filters = editing_service._editing_intro_video_filters(
            1080,
            1920,
            is_intro_clip=False,
            overlay_ass_file=Path("work") / "up_next.ass",
        )

        joined = ",".join(filters)
        self.assertNotIn("drawbox=", joined)
        self.assertNotIn("subtitles=", joined)


if __name__ == "__main__":
    unittest.main()
