from pathlib import Path
from contextlib import contextmanager

import pytest

from app.auth import middleware as auth_middleware
from app.backend.runtime import create_backend_module
import run_production


@pytest.fixture(scope="module")
def backend():
    return create_backend_module("test_public_deployment_security_backend")


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/watch?v=abcdefghijk",
        "https://youtube.com.attacker.test/watch?v=abcdefghijk",
        "https://127.0.0.1/watch?v=abcdefghijk",
        "https://user:password@youtube.com/watch?v=abcdefghijk",
        "https://www.youtube.com:8443/watch?v=abcdefghijk",
    ],
)
def test_youtube_url_validator_rejects_ssrf_inputs(backend, url):
    with pytest.raises(ValueError):
        backend._validate_youtube_url(url)


def test_youtube_url_validator_returns_canonical_https_url(backend):
    assert backend._validate_youtube_url(
        "https://youtu.be/abcdefghijk?feature=shared"
    ) == "https://www.youtube.com/watch?v=abcdefghijk"


def test_youtube_metadata_urls_are_canonical_and_channel_ssrf_is_rejected(backend):
    assert backend._video_from_ytdlp_info({"id": "abcdefghijk", "webpage_url": "https://evil.test/a"})["url"] == "https://www.youtube.com/watch?v=abcdefghijk"
    assert backend._is_allowed_youtube_host_url("https://www.youtube.com/channel/abc")
    assert not backend._is_allowed_youtube_host_url("https://127.0.0.1/channel/abc")


def test_v026_declares_multi_user_ownership_and_scoped_uniqueness():
    migration = Path("app/db/migrations/postgresql/V026__multi_user_isolation.sql").read_text(encoding="utf-8")
    for table in (
        "file_records",
        "app_notifications",
        "youtube_video_groups",
        "youtube_videos",
        "youtube_search_jobs",
        "published_youtube_materials",
        "scheduled_publish_tasks",
        "youtube_video_deletions",
    ):
        assert f"ALTER TABLE {table}" in migration
    assert "UNIQUE (owner_user_id, video_id)" in migration
    assert "youtube_video_groups (owner_user_id, LOWER(name))" in migration
    assert "V026 requires an active administrator" in migration


def test_public_payload_redacts_server_paths_and_commands():
    backend = create_backend_module()
    payload = backend._redact_public_paths({
        "assetId": "asset-1",
        "filePath": "E:\\private\\video.mp4",
        "nested": {"processedFilePath": "E:\\private\\processed.mp4", "publishCommand": "secret"},
        "items": [{"errorDetail": "internal", "title": "safe"}],
    })

    assert payload == {"assetId": "asset-1", "nested": {}, "items": [{"title": "safe"}]}


def test_asset_lookup_uses_owner_and_hides_cross_user_record(backend, monkeypatch):
    class Cursor:
        def execute(self, _sql, values):
            self.values = values

        def fetchone(self):
            return {"asset_id": "asset-1", "owner_user_id": 1} if self.values == ("asset-1", 1) else None

    class Connection:
        row_factory = None

        def cursor(self):
            return Cursor()

    @contextmanager
    def connect(*_args, **_kwargs):
        yield Connection()

    monkeypatch.setattr(backend, "_db_connect", connect)
    with pytest.raises(LookupError, match="素材不存在"):
        backend._owned_asset_path("asset-1", 2)


def test_material_path_resolves_relative_youtube_download_at_project_root(backend, monkeypatch, tmp_path):
    download_dir = tmp_path / "videos" / "youtube"
    source_file = download_dir / "source.mp4"
    download_dir.mkdir(parents=True)
    source_file.write_bytes(b"video")
    monkeypatch.setattr(backend, "BASE_DIR", tmp_path)
    monkeypatch.setattr(backend, "YOUTUBE_DOWNLOAD_DIR", download_dir)
    monkeypatch.setattr(backend, "YOUTUBE_PROCESSED_DIR", tmp_path / "videos" / "processed")

    resolved = backend._material_file_path({
        "source_type": "youtube_download",
        "storage_key": "videos/youtube/source.mp4",
    })

    assert resolved == source_file


def test_hsts_trusts_forwarded_https_only_from_configured_proxy(backend, monkeypatch):
    backend.app.config["AUTH_TEST_BYPASS"] = True
    monkeypatch.setattr(auth_middleware, "AUTH_TRUSTED_PROXY_CIDRS", ["127.0.0.1/32"])
    response = backend.app.test_client().get("/auth/public-config", headers={"X-Forwarded-Proto": "https"})
    assert response.headers["Strict-Transport-Security"].startswith("max-age=31536000")

    monkeypatch.setattr(auth_middleware, "AUTH_TRUSTED_PROXY_CIDRS", ["10.0.0.0/8"])
    response = backend.app.test_client().get("/auth/public-config", headers={"X-Forwarded-Proto": "https"})
    assert "Strict-Transport-Security" not in response.headers


def test_flask_serves_built_frontend_without_exposing_protected_media(backend, monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text("<html>Vidferry</html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('app')", encoding="utf-8")

    backend.app.config["AUTH_TEST_BYPASS"] = False
    monkeypatch.setattr(backend, "_FRONTEND_DIST_DIR", tmp_path)
    client = backend.app.test_client()

    assert client.get("/").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/asset-1/content").status_code == 401


def test_production_config_accepts_only_explicit_secure_values(monkeypatch):
    monkeypatch.setattr(run_production, "AUTH_COOKIE_SECURE", True)
    monkeypatch.setattr(run_production, "AUTH_CSRF_SECRET", "x" * 40)
    monkeypatch.setattr(run_production, "CORS_ORIGINS", ["https://vidferry.example.com"])
    monkeypatch.setattr(run_production, "AUTH_TRUSTED_PROXY_CIDRS", ["127.0.0.1/32"])
    monkeypatch.setattr(run_production, "AUTH_ALLOW_COOKIE_EXPORT", False)
    monkeypatch.setenv("VIDFERRY_AUTH_SECRET", "x" * 40)
    run_production._validate_production_config()
