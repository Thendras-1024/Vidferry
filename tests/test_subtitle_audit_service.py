from app.backend.runtime import load_backend_namespace


class _Result:
    def __init__(self, one=None, many=None):
        self.one = one
        self.many = many or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class _AuditConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, _params=()):
        if "FROM youtube_workflow_jobs j LEFT JOIN" in sql:
            return _Result({
                "workflow_job_id": "job-1", "workflow_video_id": "video-1", "workflow_title": "Video",
                "job_status": "failed", "job_started_at": "", "job_created_at": "", "job_updated_at": "",
                "comment_burn_enabled": 1, "has_comment_audit": 1, "initial_segments": "[]", "reviewed_segments": "[]",
                "review_batches": "[]", "review_status": "not_recorded", "fallback_segment_count": 0,
            })
        if "youtube_workflow_llm_usage_events" in sql:
            return _Result(many=[])
        if "youtube_workflow_events" in sql:
            return _Result(many=[
                {"metadata": '{"candidateCount": 100}'},
                {"metadata": '{"reviewItems": [{"id": "comment-1", "status": "pending"}]}'},
            ])
        raise AssertionError(sql)


def test_subtitle_audit_keeps_fetched_comment_review_items_when_review_is_interrupted():
    namespace = load_backend_namespace({})
    namespace["init_database_tables"] = lambda: None
    namespace["_db_connect"] = lambda **_kwargs: _AuditConnection()

    detail = namespace["get_subtitle_audit_detail"]("job-1")

    assert detail["commentReviewItems"] == [{"id": "comment-1", "status": "pending"}]
