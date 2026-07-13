import unittest
from pathlib import Path

from app import publish_runner
from app.core import publish_execution


class TencentPublishRunnerTests(unittest.TestCase):
    def test_publish_runner_accepts_tencent_draft(self):
        parser = publish_runner.build_parser()
        args = parser.parse_args(
            [
                "--platform",
                "tencent",
                "--account-file",
                "cookiesFile/tencent_creator.json",
                "--file",
                "videoFile/demo.mp4",
                "--title",
                "视频标题",
                "--draft",
            ]
        )

        self.assertEqual(args.platform, "tencent")
        self.assertTrue(args.draft)
        self.assertFalse(args.headless)

    def test_workflow_command_maps_platform_2_to_tencent(self):
        publish_execution.sys = __import__("sys")
        publish_execution.platform_name = lambda platform_type: "视频号"
        publish_execution.normalize_bilibili_tid = lambda value: value or 21

        command = publish_execution._workflow_publish_runner_command(
            {
                "platformType": 2,
                "platformName": "视频号",
                "accountPath": Path("cookiesFile/tencent_creator.json"),
                "absoluteFiles": [Path("videoFile/demo.mp4")],
                "title": "视频标题",
                "description": "视频简介",
                "tags": ["测试", "视频"],
                "publishDatetimes": [0],
                "thumbnailPath": "",
                "productLink": "",
                "productTitle": "",
                "bilibiliTid": "",
                "headless": False,
                "debug": True,
                "isDraft": True,
            }
        )

        self.assertIn("tencent", command)
        self.assertIn("--draft", command)


if __name__ == "__main__":
    unittest.main()
