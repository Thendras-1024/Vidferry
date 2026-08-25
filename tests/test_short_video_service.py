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


def test_short_video_async_writes_keep_project_ownership_contract():
    source = Path("app/core/short_video_service.py").read_text(encoding="utf-8")

    assert "SELECT * FROM short_video_projects WHERE id = %s AND owner_user_id = %s" in source
    assert "def _set_project_status(project_id, owner_id, status, message, **updates):" in source
    assert "WHERE id = %s AND owner_user_id = %s" in source
    assert source.count("WHERE candidate.id = %s AND candidate.project_id = %s") == 2
    assert "owner_user_id=owner_id" in source


def test_short_video_api_passes_owner_to_status_updates():
    source = Path("app/api/short_video.py").read_text(encoding="utf-8")

    assert "_set_project_status(project_id, owner_id, \"searching\"" in source
    review_section = source.split("def short_video_candidate_review", 1)[1].split("def short_video_candidate_asset", 1)[0]
    assert "get_short_video_project(project_id)" in review_section


def test_short_video_render_uses_submitted_owner_without_request_context(monkeypatch):
    from app.backend.runtime import create_backend_module

    backend = create_backend_module()
    project = {"id": "project-a", "topic": "测试", "bgm_track_id": None}
    candidates = [
        {"id": "candidate-a", "project_id": "project-a", "source_url": "https://example.test/source-a", "clip_duration_seconds": 8},
        {"id": "candidate-b", "project_id": "project-a", "source_url": "https://example.test/source-b", "clip_duration_seconds": 8},
    ]
    writes, material_owners, render_owners = [], [], []

    class Cursor:
        def execute(self, sql, params=()):
            self.sql = sql
            self.params = params

        def fetchall(self):
            return candidates if "short_video_candidates" in self.sql else []

    class Connection:
        row_factory = False

        def cursor(self):
            return Cursor()

        def execute(self, sql, params=()):
            writes.append((sql, params))

    connection = Connection()

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(backend, "_ensure_tables", lambda: None)
    monkeypatch.setattr(backend, "_db_connect", connect)
    monkeypatch.setattr(backend, "_project", lambda _cursor, project_id, owner_id: project if (project_id, owner_id) == ("project-a", 22) else None)
    monkeypatch.setattr(backend, "_render_concat", lambda _project, _candidates, _bgm, owner_id: render_owners.append(owner_id) or Path("output.mp4"))
    monkeypatch.setattr(backend, "register_material", lambda _output, **kwargs: material_owners.append(kwargs["owner_user_id"]) or {"id": 99})

    result = backend.run_short_video_render("project-a", 22)

    assert result == {"projectId": "project-a", "status": "success", "materialId": 99}
    assert render_owners == [22]
    assert material_owners == [22]
    assert all(params[-1] == 22 for _, params in writes)
