import datetime

from app.backend.runtime import load_backend_namespace


class _EmptySearchJobsCursor:
    def execute(self, _sql, _params=()):
        pass

    def fetchall(self):
        return []


class _EmptySearchJobsConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _EmptySearchJobsCursor()


def test_recover_interrupted_youtube_search_jobs_uses_private_datetime_module():
    namespace = load_backend_namespace({})
    namespace["init_youtube_video_table"] = lambda: None
    namespace["_db_connect"] = lambda **_kwargs: _EmptySearchJobsConnection()

    assert namespace["_datetime"] is datetime
    assert namespace["datetime"] is datetime
    assert namespace["_comment_datetime"] is datetime.datetime
    assert namespace["recover_interrupted_youtube_search_jobs"]() == []


def test_custom_subtitle_command_disables_saved_comment_burn_setting():
    namespace = load_backend_namespace({})
    namespace["SUBTITLE_COMMAND_TEMPLATE"] = "ffmpeg -i {input} {output}"

    settings = namespace["_normalize_workflow_settings"]({
        "processVersion": namespace["PROCESS_VERSION_EDITING"],
        "commentBurnEnabled": True,
    })

    assert settings["commentBurnEnabled"] is False
    assert namespace["_comment_burn_available"]() is False
