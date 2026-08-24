from pathlib import Path

from app.cli import utils as cli_utils


def test_cli_account_files_use_cookies_file_without_creating_legacy_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_utils, "resolve_runtime_home", lambda: tmp_path)

    account_file = cli_utils.resolve_account_file("douyin", "default")

    assert account_file == tmp_path / "cookiesFile" / "cli" / "douyin_default.json"
    assert account_file.parent.is_dir()
    assert not (tmp_path / "cookies").exists()


def test_tencent_uploader_keeps_absolute_account_path_and_uses_legacy_cookie_subdirectory(tmp_path, monkeypatch):
    from uploader.tencent_uploader import main as tencent_main

    monkeypatch.setattr(tencent_main, "BASE_DIR", tmp_path)
    absolute_path = tmp_path / "external" / "account.json"

    assert tencent_main._resolve_account_file(absolute_path) == str(absolute_path)
    assert tencent_main._resolve_account_file("account.json") == str(
        (tmp_path / "cookiesFile" / "legacy" / "tencent_uploader" / "account.json").resolve()
    )
    assert not (tmp_path / "cookies").exists()
