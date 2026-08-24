from pathlib import Path

from app.backend.runtime import create_backend_module


def test_youtube_material_paths_keep_downloads_outside_and_processed_videos_inside_library(monkeypatch, tmp_path):
    backend = create_backend_module("test_youtube_material_paths_backend")
    monkeypatch.setattr(backend, "BASE_DIR", tmp_path)

    processed = backend._material_file_path({"source_type": "youtube_processed", "storage_key": "1/processed.mp4"})
    downloaded = backend._material_file_path({"source_type": "youtube_download", "storage_key": "videos/source.mp4"})

    assert processed == tmp_path / "videoFile" / "1" / "processed.mp4"
    assert downloaded == tmp_path / "videos" / "source.mp4"


def test_asset_content_supports_byte_ranges(monkeypatch, tmp_path):
    backend = create_backend_module("test_asset_content_range_backend")
    video_path = Path(tmp_path / "preview.mp4")
    video_path.write_bytes(b"0123456789")
    monkeypatch.setattr(backend, "_current_account_owner_id", lambda: 1)
    monkeypatch.setattr(backend, "_owned_asset_path", lambda *_args: video_path)

    with backend.app.test_request_context("/assets/preview/content", headers={"Range": "bytes=2-5"}):
        response = backend.get_asset_content("preview")
        response.direct_passthrough = False

    assert response.status_code == 206
    assert response.get_data() == b"2345"


def test_cached_source_title_is_attached_without_waiting_for_backfill():
    backend = create_backend_module("test_youtube_chinese_title_backend")

    class Cursor:
        def execute(self, *_args):
            return self

        def fetchall(self):
            return [{"video_id": "video-1", "metadata": '{"sourceTitleZh": "中文标题"}'}]

    videos = [{"id": "video-1", "title": "Original title"}, {"id": "video-2", "title": "Other title"}]

    assert backend._attach_source_title_translations(Cursor(), videos, 1)
    assert videos == [
        {"id": "video-1", "title": "Original title", "chineseTitle": "中文标题"},
        {"id": "video-2", "title": "Other title", "chineseTitle": ""},
    ]


def test_source_title_candidates_query_only_the_current_page():
    backend = create_backend_module("test_youtube_title_page_candidates_backend")

    class Cursor:
        sql = ""
        params = ()

        def execute(self, sql, params=()):
            self.sql = sql
            self.params = params
            return self

        def fetchall(self):
            return [{"video_id": "video-1", "title": "Original title"}]

    cursor = Cursor()
    candidates = backend._source_title_translation_candidates(
        cursor,
        [{"id": "video-1", "title": "Original title"}, {"id": "video-2", "title": "Other title"}],
        1,
        20,
    )
    assert candidates == [{"video_id": "video-1", "title": "Original title"}]
    assert "WITH page" in cursor.sql
    assert "FROM youtube_videos" not in cursor.sql


def test_agent_video_card_prefers_chinese_title_and_preserves_original_title():
    backend = create_backend_module("test_agent_chinese_title_backend")

    item = backend._agent_video_status_card_item({
        "id": "video-1",
        "title": "Original title",
        "chineseTitle": "中文标题",
    })

    assert item["title"] == "中文标题"
    assert item["originalTitle"] == "Original title"
    assert item["videoContext"]["title"] == "中文标题"
    assert item["videoContext"]["originalTitle"] == "Original title"
