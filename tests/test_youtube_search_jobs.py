import datetime
import html
import json
import re
import sqlite3
import tempfile
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _exec_file(namespace, relative_path):
    path = ROOT / relative_path
    source = path.read_text(encoding="utf-8-sig")
    exec(compile(source, str(path), "exec"), namespace)


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


def _load_search_namespace(database_path):
    module = types.ModuleType("youtube_search_job_test_module")

    @contextmanager
    def db_connect(*, row_factory=False):
        connection = sqlite3.connect(database_path, timeout=5)
        if row_factory:
            connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    namespace = module.__dict__
    namespace.update({
        "datetime": datetime,
        "html": html,
        "json": json,
        "re": re,
        "sqlite3": sqlite3,
        "urllib": urllib,
        "uuid": uuid,
        "Path": Path,
        "_db_connect": db_connect,
        "_format_count": lambda value: str(value or ""),
        "_format_iso_date": lambda value: str(value or ""),
        "_format_subscribers_w": lambda value: str(value or ""),
        "_parse_upload_date": lambda value: str(value or ""),
        "_parse_json_object": lambda value: {},
        "_parse_publish_draft": lambda value, analysis: {},
        "_youtube_thumbnail_url": lambda video_id: "",
        "_published_youtube_identity_sets": lambda cursor: (set(), set()),
        "_assert_no_active_youtube_job": lambda cursor, video_id: None,
        "_find_latest_youtube_material": lambda cursor, video_id, category: None,
        "_row_to_material": lambda material: material,
        "_archive_published_material": lambda *args, **kwargs: None,
        "_now_iso": lambda: datetime.datetime.now().isoformat(timespec="seconds"),
        "_base_ytdlp_opts": lambda **kwargs: {},
        "YOUTUBE_FALLBACK_QUERIES": [],
        "YOUTUBE_TRANSCRIPT_DIR": Path(database_path).parent,
        "WORKFLOW_ERROR_DELETE_PROCESSED_EXISTS": "processed_exists",
        "WORKFLOW_ERROR_DELETE_DOWNLOAD_EXISTS": "download_exists",
        "backend_logger": _Logger(),
    })

    class WorkflowConflictError(ValueError):
        def __init__(self, message, error_code, error_type="", data=None):
            super().__init__(message)
            self.error_code = error_code
            self.error_type = error_type
            self.data = data or {}

    namespace["WorkflowConflictError"] = WorkflowConflictError
    _exec_file(namespace, "app/db/models.py")

    def init_youtube_video_table():
        with db_connect() as connection:
            namespace["ensure_youtube_video_table"](connection.cursor())
            connection.execute('''
            CREATE TABLE IF NOT EXISTS youtube_workflow_events (
                job_id TEXT,
                video_id TEXT
            )
            ''')
            connection.execute('''
            CREATE TABLE IF NOT EXISTS youtube_workflow_jobs (
                id TEXT PRIMARY KEY,
                video_id TEXT
            )
            ''')

    namespace["init_youtube_video_table"] = init_youtube_video_table
    namespace["init_youtube_workflow_table"] = init_youtube_video_table
    _exec_file(namespace, "app/core/youtube_service.py")
    _exec_file(namespace, "app/core/youtube_search_service.py")
    namespace["_published_youtube_identity_sets"] = lambda cursor: (set(), set())
    return module


def _video(video_id):
    return {
        "id": video_id,
        "title": f"First time in China {video_id}",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "channel": "channel",
    }


class YoutubeSearchJobTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "database.db"
        self.service = _load_search_namespace(self.database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_worker_updates_progress_after_every_candidate(self):
        self.service.save_one_youtube_video(_video("existing"), "seed")
        job = self.service.create_youtube_search_job("China travel", 5)
        candidates = [_video("new-1"), _video("existing"), _video("new-2")]
        self.service._search_youtube_with_ytdlp = lambda query, limit: candidates
        self.service._enrich_video_from_watch_page = lambda video: video
        self.assertEqual(self.service.get_youtube_search_job(job["jobId"])["status"], "queued")

        def search_with_running_assertion(query, limit):
            self.assertEqual(self.service.get_youtube_search_job(job["jobId"])["status"], "running")
            return candidates

        self.service._search_youtube_with_ytdlp = search_with_running_assertion

        snapshots = []
        process_candidate = self.service._process_youtube_search_candidate

        def tracked_process(*args):
            decision = process_candidate(*args)
            snapshots.append(self.service.get_youtube_search_job(job["jobId"])["found"])
            return decision

        self.service._process_youtube_search_candidate = tracked_process
        self.service.run_youtube_search_job(job["jobId"])
        result = self.service.get_youtube_search_job(job["jobId"])

        self.assertEqual(snapshots, [1, 2, 3])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["found"], 3)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["duplicate"], 1)
        self.assertEqual(
            result["found"],
            result["created"] + result["duplicate"] + result["skipped"] + result["failed"],
        )

    def test_same_video_is_counted_only_once_per_job(self):
        job = self.service.create_youtube_search_job("China travel", 2)
        self.service._claim_youtube_search_job(job["jobId"])

        first = self.service._process_youtube_search_candidate(job["jobId"], 1, _video("same"))
        second = self.service._process_youtube_search_candidate(job["jobId"], 2, _video("same"))
        result = self.service.get_youtube_search_job(job["jobId"])

        self.assertEqual(first, "created")
        self.assertIsNone(second)
        self.assertEqual(result["found"], 1)
        self.assertEqual(result["created"], 1)

    def test_delete_blocks_old_job_but_new_job_can_reimport(self):
        video = _video("delete-race")
        old_job = self.service.create_youtube_search_job("China travel", 1)
        self.service._claim_youtube_search_job(old_job["jobId"])
        self.service.save_one_youtube_video(video, "seed")
        self.service.delete_youtube_video_record(video["id"])

        old_decision = self.service._process_youtube_search_candidate(old_job["jobId"], 1, video)
        old_result = self.service.get_youtube_search_job(old_job["jobId"])
        new_job = self.service.create_youtube_search_job("China travel", 1)
        self.service._claim_youtube_search_job(new_job["jobId"])
        new_decision = self.service._process_youtube_search_candidate(new_job["jobId"], 1, video)

        self.assertEqual(old_decision, "skipped")
        self.assertEqual(old_result["skipped"], 1)
        self.assertEqual(new_decision, "created")


class YoutubeSearchJobApiTests(unittest.TestCase):
    def test_create_route_returns_202_and_submits_background_job(self):
        class FakeApp:
            def route(self, *args, **kwargs):
                return lambda function: function

        class FakeRequest:
            @staticmethod
            def get_json(silent=True):
                return {"query": "China travel", "limit": 20}

        submitted = []
        module = types.ModuleType("youtube_search_api_test_module")
        module.__dict__.update({
            "app": FakeApp(),
            "request": FakeRequest(),
            "YOUTUBE_DEFAULT_QUERY": "default",
            "get_workflow_settings": lambda: {},
            "_parse_positive_int": lambda value, default, minimum, maximum: max(minimum, min(int(value), maximum)),
            "create_youtube_search_job": lambda query, requested: {
                "jobId": "job-1",
                "query": query,
                "requested": requested,
                "status": "queued",
            },
            "run_youtube_search_job": lambda job_id: None,
            "_submit_background_task": lambda resource, target, job_id: submitted.append((resource, job_id)),
            "_json_response": lambda code=200, msg="success", data=None, status=200: (
                {"code": code, "msg": msg, "data": data},
                status,
            ),
            "backend_logger": _Logger(),
        })
        _exec_file(module.__dict__, "app/api/youtube.py")

        payload, status = module.create_youtube_search_job_route()

        self.assertEqual(status, 202)
        self.assertEqual(payload["data"]["jobId"], "job-1")
        self.assertEqual(submitted, [("search", "job-1")])


if __name__ == "__main__":
    unittest.main()
