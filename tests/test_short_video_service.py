from pathlib import Path
from contextlib import contextmanager


def _service_namespace():
    source = Path("app/core/short_video_service.py").read_text(encoding="utf-8")
    source = source.split("def _search_candidates", 1)[0]
    namespace = {}
    exec(compile(source, "short_video_service.py", "exec"), namespace)
    return namespace


def test_short_video_license_requires_creative_commons_or_whitelist():
    service = _service_namespace()
    assert service["_license_basis"]({"license": "Creative Commons Attribution", "channel": "Other"}, set())[1] == "Creative Commons"
    assert service["_license_basis"]({"license": "Standard YouTube License", "channel": "Allowed Channel"}, {"allowed channel"})[1] == "授权频道白名单"
    assert service["_license_basis"]({"license": "Standard YouTube License", "channel": "Other"}, set())[1] == ""


def test_short_video_requires_native_vertical_source():
    service = _service_namespace()
    assert service["_video_is_vertical"]({"width": 1080, "height": 1920}) is True
    assert service["_video_is_vertical"]({"width": 1920, "height": 1080}) is False
    assert service["_video_is_vertical"]({"width": 0, "height": 1920}) is False


def test_short_video_transition_set_is_fixed():
    service = _service_namespace()
    assert service["_VALID_TRANSITIONS"] == {"cut", "fade", "slideleft", "zoomin"}


def test_short_video_metadata_filter_supports_compact_chinese_topics():
    service = _service_namespace()
    assert service["_topic_matches_metadata"]({"title": "搞笑 宠物反应"}, "搞笑宠物") is True
    assert service["_topic_matches_metadata"]({"title": "风景纪录片"}, "搞笑宠物") is False


def test_short_video_project_create_uses_named_rows_and_default_candidate_count():
    service = _service_namespace()
    project = {"id": "project-1", "owner_user_id": 7, "target_count": 10, "target_duration_seconds": 45,
               "transition_type": "cut", "bgm_track_id": None, "keep_original_audio": 0, "output_file_path": "", "output_material_id": None}

    class Cursor:
        def execute(self, sql, params=()):
            self.sql = sql
            self.params = params
        def fetchone(self):
            return project
        def fetchall(self):
            return []

    class Connection:
        row_factory = False
        def cursor(self):
            return Cursor()

    connection = Connection()

    @contextmanager
    def connect():
        yield connection

    service.update({"_ensure_tables": lambda: None, "_db_connect": connect, "_owner_id": lambda: 7})
    created = service["create_short_video_project"]({"topic": "搞笑宠物"})
    assert connection.row_factory is True
    assert created["targetCount"] == 10
