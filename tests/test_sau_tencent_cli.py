import asyncio
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sau_cli


class TencentCliTests(unittest.TestCase):
    def test_build_parser_accepts_tencent_login_default_headed(self):
        parser = sau_cli.build_parser()
        args = parser.parse_args(["tencent", "login", "--account", "creator"])
        self.assertEqual(args.platform, "tencent")
        self.assertEqual(args.action, "login")
        self.assertFalse(args.headless)

    def test_build_parser_accepts_tencent_upload_video_draft(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "demo.mp4"
            video_path.write_bytes(b"video")

            parser = sau_cli.build_parser()
            args = parser.parse_args(
                [
                    "tencent",
                    "upload-video",
                    "--account",
                    "creator",
                    "--file",
                    str(video_path),
                    "--title",
                    "视频标题",
                    "--desc",
                    "视频简介",
                    "--draft",
                ]
            )

        self.assertTrue(args.draft)
        self.assertFalse(args.headless)

    def test_dispatch_tencent_upload_video_builds_request(self):
        args = Namespace(
            platform="tencent",
            action="upload-video",
            account="creator",
            file=Path("demo.mp4"),
            title="视频标题",
            desc="视频简介",
            tags="测试,视频",
            schedule=0,
            thumbnail=None,
            draft=True,
            debug=False,
            headless=False,
        )
        with patch("sau_cli.upload_tencent_video", new=AsyncMock()) as mock_upload:
            code = asyncio.run(sau_cli.dispatch(args))

        request = mock_upload.await_args.args[0]
        self.assertEqual(code, 0)
        self.assertEqual(request.title, "视频标题")
        self.assertEqual(request.description, "视频简介")
        self.assertEqual(request.tags, ["测试", "视频"])
        self.assertTrue(request.is_draft)
        self.assertFalse(request.headless)

    def test_dispatch_tencent_check_prints_valid(self):
        args = Namespace(platform="tencent", action="check", account="creator")
        with patch("sau_cli.check_tencent_account", new=AsyncMock(return_value=True)):
            code = asyncio.run(sau_cli.dispatch(args))
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
