import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sau_backend as backend


class MaterialWorkflowConsistencyTests(unittest.TestCase):
    def test_project_relative_youtube_thumbnail_is_served(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            thumbnail = base_dir / "videos" / "youtube" / "video-id.webp"
            thumbnail.parent.mkdir(parents=True)
            thumbnail.write_bytes(b"thumbnail")
            with (
                patch.object(backend, "BASE_DIR", base_dir),
                patch.object(backend, "YOUTUBE_DOWNLOAD_DIR", thumbnail.parent),
                patch.object(backend, "YOUTUBE_PROCESSED_DIR", base_dir / "videos" / "processed"),
            ):
                response = backend.app.test_client().get("/getFile?filename=videos\\youtube\\video-id.webp")
                status_code = response.status_code
                content = response.data
                response.close()

        self.assertEqual(status_code, 200)
        self.assertEqual(content, b"thumbnail")

    def test_terminal_job_from_another_version_is_not_attached_to_material(self):
        material = {"source_video_id": "video-id", "processVersion": "translation_v1"}
        failed_editing_job = {"status": "failed", "processVersion": "editing_v1"}
        job = backend._material_workflow_job(
            material,
            {"video-id": failed_editing_job},
            {("video-id", "editing_v1"): failed_editing_job},
        )

        self.assertIsNone(job)

    def test_active_job_from_another_version_remains_visible(self):
        material = {"source_video_id": "video-id", "processVersion": "translation_v1"}
        active_editing_job = {"status": "running", "processVersion": "editing_v1"}
        job = backend._material_workflow_job(
            material,
            {"video-id": active_editing_job},
            {("video-id", "editing_v1"): active_editing_job},
        )

        self.assertEqual(job, active_editing_job)

    def test_reset_history_cleanup_targets_only_terminal_jobs_of_requested_version(self):
        executed = []

        class Cursor:
            rowcount = 2

            def execute(self, statement, values=()):
                executed.append((statement, values))

        deleted = backend._delete_reset_youtube_workflow_history(
            Cursor(),
            "video-id",
            "editing_v1",
        )

        self.assertEqual(deleted, 2)
        self.assertEqual(len(executed), 2)
        self.assertTrue(all("status NOT IN ('queued', 'running')" in statement for statement, _ in executed))
        self.assertTrue(all(values == ["video-id", "editing_v1"] for _, values in executed))


if __name__ == "__main__":
    unittest.main()
