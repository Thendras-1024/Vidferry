from contextlib import contextmanager

from app.backend.runtime import create_backend_module


def test_agent_candidate_search_is_owner_scoped_and_keeps_score_order(monkeypatch):
    backend = create_backend_module()
    videos = [
        {"id": "low", "score": 10},
        {"id": "mine", "score": 90},
        {"id": "other", "score": 50},
        {"id": "high", "score": 100},
    ]
    queries = []

    class Cursor:
        def execute(self, sql, params=()):
            queries.append((sql, params))
            self.rows = [{"video_id": "mine"}] if "owner_user_id" in sql else [
                {"video_id": "mine"},
                {"video_id": "other"},
            ]
            return self

        def fetchall(self):
            return self.rows

    @contextmanager
    def connect(**_kwargs):
        yield type("Connection", (), {"cursor": lambda self: Cursor()})()

    monkeypatch.setattr(backend, "_agent_current_user_id", lambda: 42)
    monkeypatch.setattr(backend, "_search_youtube_with_ytdlp", lambda *_args: videos)
    monkeypatch.setattr(backend, "init_youtube_video_table", lambda: None)
    monkeypatch.setattr(backend, "_db_connect", connect)
    monkeypatch.setattr(backend, "_agent_enrich_candidate_metadata", lambda item: dict(item))
    monkeypatch.setattr(backend, "_enrich_video_metadata", lambda item, *_args, **_kwargs: dict(item))
    monkeypatch.setattr(backend, "_candidate_metadata_score", lambda item: (item["score"], []))

    result = backend.search_youtube_candidates("topic", limit=3)

    assert [item["id"] for item in result["items"]] == ["high", "other", "low"]
    assert result["excludedExisting"] == 1
    assert len(queries) == 1
    assert "owner_user_id = %s" in queries[0][0]
    assert queries[0][1][0] == 42
