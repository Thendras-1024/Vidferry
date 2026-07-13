import tempfile
import unittest
from pathlib import Path
from types import ModuleType

import app.config as config


def _load_watermark_module():
    module = ModuleType("watermark_test_module")
    module.__dict__.update(vars(config))
    module.__dict__["Path"] = Path
    for relative_path in ("app/core/settings_service.py", "app/core/subtitle_service.py"):
        path = Path(__file__).resolve().parents[1] / relative_path
        exec(compile(path.read_text(encoding="utf-8-sig"), str(path), "exec"), module.__dict__)
    module._subtitle_language_meta = lambda value: ("zh-CN", {"label": "中文"})
    module._subtitle_size_config = lambda value: ("large", {"scale": 1.0})
    module._normalize_translator_label = lambda value: str(value or "Vidferry翻译")[:20]
    module._normalize_watermark_text = lambda value: str(value or "").strip()[:16]
    module._normalize_process_version = lambda value: str(value or "translation_v1")
    module.PROCESS_VERSION_EDITING = "editing_v1"
    return module


class WatermarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = _load_watermark_module()

    def test_settings_default_and_normalization(self):
        settings = self.backend._normalize_workflow_settings({
            "watermarkEnabled": True,
            "watermarkText": "  自定义水印  ",
        })

        self.assertTrue(settings["watermarkEnabled"])
        self.assertEqual(settings["watermarkText"], "自定义水印")
        self.assertFalse(self.backend._default_workflow_settings()["watermarkEnabled"])
        self.assertEqual(self.backend._normalize_workflow_settings({"watermarkText": "x"})["watermarkText"], "")
        self.assertEqual(len(self.backend._normalize_workflow_settings({"watermarkText": "x" * 20})["watermarkText"]), 16)

    def test_ass_has_full_duration_watermark_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ass_file = Path(tmp_dir) / "watermark.ass"
            self.backend._build_ass_file(
                {"watermarkEnabled": True, "watermarkText": "{测试}\\水印"},
                [],
                ass_file,
                123.4,
                {"width": 1080, "height": 1920},
                include_subtitles=False,
            )
            content = ass_file.read_text(encoding="utf-8")

        self.assertIn("Style: Watermark", content)
        self.assertIn(",0,-15,1,1,0,9,", content)
        self.assertIn("0:00:00.00,0:02:03.40,Watermark", content)
        self.assertIn(r"\{测试\}\\水印", content)
        self.assertNotIn(",Info,,", content)

    def test_editing_version_defers_watermark_to_final_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ass_file = Path(tmp_dir) / "editing.ass"
            self.backend._build_ass_file(
                {"watermarkEnabled": True, "processVersion": "editing_v1"},
                [], ass_file, 10, {"width": 1080, "height": 1920},
            )
            content = ass_file.read_text(encoding="utf-8")

        self.assertNotIn(",Watermark,,", content)

    def test_ass_omits_watermark_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ass_file = Path(tmp_dir) / "no-watermark.ass"
            self.backend._build_ass_file(
                {"watermarkEnabled": False}, [], ass_file, 10,
                {"width": 1920, "height": 1080}, include_subtitles=False,
            )
            content = ass_file.read_text(encoding="utf-8")

        self.assertNotIn(",Watermark,,", content)


if __name__ == "__main__":
    unittest.main()
