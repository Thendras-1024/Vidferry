import json
import os
import subprocess
import sys
from types import ModuleType, SimpleNamespace

from app.backend.runtime import create_backend_module


def test_config_does_not_inject_hf_proxy_into_process_environment():
    env = os.environ.copy()
    env.update({
        "HF_PROXY": "http://hf-proxy.invalid",
        "YTDLP_PROXY": "http://ytdlp-proxy.invalid",
        "HTTP_PROXY": "http://http-proxy.invalid",
        "HTTPS_PROXY": "http://https-proxy.invalid",
        "ALL_PROXY": "http://all-proxy.invalid",
    })
    script = (
        "import json, os; import app.config; "
        "print(json.dumps({k: os.environ.get(k) for k in "
        "('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout.strip()) == {
        "HTTP_PROXY": "http://http-proxy.invalid",
        "HTTPS_PROXY": "http://https-proxy.invalid",
        "ALL_PROXY": "http://all-proxy.invalid",
    }


def test_base_ytdlp_opts_uses_default_and_local_proxy_scope(monkeypatch):
    backend = create_backend_module()
    monkeypatch.setattr(backend, "YTDLP_PROXY", "http://configured.invalid")

    assert backend._base_ytdlp_opts()["proxy"] == "http://configured.invalid"
    assert backend._base_ytdlp_opts(proxy="http://local.invalid")["proxy"] == "http://local.invalid"
    assert "proxy" not in backend._base_ytdlp_opts(proxy="")


def test_video_download_prefers_ytdlp_proxy_over_hf_proxy(monkeypatch, tmp_path):
    backend = create_backend_module()
    captured = []

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            (tmp_path / "video.mp4").write_bytes(b"video")
            return {"id": "video"}

    fake_yt_dlp = ModuleType("yt_dlp")
    fake_yt_dlp.YoutubeDL = FakeYoutubeDL
    fake_yt_dlp.utils = SimpleNamespace(DownloadError=RuntimeError)
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_yt_dlp)
    monkeypatch.setattr(backend, "YOUTUBE_DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(backend, "YTDLP_PROXY", "http://configured.invalid")
    monkeypatch.setattr(backend, "HF_PROXY", "http://hf.invalid")
    monkeypatch.setattr(backend, "YTDLP_DOWNLOAD_ATTEMPTS", 1)
    monkeypatch.setattr(backend, "_resolve_ffmpeg_command", lambda: "ffmpeg")

    backend._download_youtube_video({"id": "job", "videoId": "video", "url": "https://youtube.invalid/watch"})

    assert captured[0]["proxy"] == "http://configured.invalid"


def test_video_download_uses_hf_proxy_only_when_ytdlp_proxy_is_empty(monkeypatch, tmp_path):
    backend = create_backend_module()
    captured = []

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            (tmp_path / "video.mp4").write_bytes(b"video")
            return {"id": "video"}

    fake_yt_dlp = ModuleType("yt_dlp")
    fake_yt_dlp.YoutubeDL = FakeYoutubeDL
    fake_yt_dlp.utils = SimpleNamespace(DownloadError=RuntimeError)
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_yt_dlp)
    monkeypatch.setattr(backend, "YOUTUBE_DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(backend, "YTDLP_PROXY", "")
    monkeypatch.setattr(backend, "HF_PROXY", "http://hf.invalid")
    monkeypatch.setattr(backend, "YTDLP_DOWNLOAD_ATTEMPTS", 1)
    monkeypatch.setattr(backend, "_resolve_ffmpeg_command", lambda: "ffmpeg")

    backend._download_youtube_video({"id": "job", "videoId": "video", "url": "https://youtube.invalid/watch"})

    assert captured[0]["proxy"] == "http://hf.invalid"


def test_google_translation_does_not_receive_hf_proxy_from_environment(monkeypatch):
    backend = create_backend_module()
    captured = []
    monkeypatch.setattr(backend, "HF_PROXY", "http://hf.invalid")
    monkeypatch.setattr(backend, "YTDLP_PROXY", "")

    def fake_google_translate(text, source, target, timeout, proxy):
        captured.append(proxy)
        return "译文"

    monkeypatch.setattr(backend, "_google_translate_text", fake_google_translate)

    translated = backend._translate_segments(
        [{"text": "source text"}], "zh-CN", source_language="en",
    )

    assert translated[0]["subtitle"] == "译文"
    assert captured == ["http://hf.invalid"]
    assert os.environ.get("HTTP_PROXY") != "http://hf.invalid"
