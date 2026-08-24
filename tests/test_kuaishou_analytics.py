from datetime import date, datetime
from pathlib import Path

import pytest

from app.backend.runtime import create_backend_module


def test_official_list_maps_fields_and_paginates(monkeypatch):
    backend = create_backend_module()
    monkeypatch.setitem(backend.__dict__, "_ks_load_official_auth", lambda *_: ("app", "token"))
    calls = []

    def fake_get(_url, params):
        calls.append(params.copy())
        if len(calls) == 1:
            return {"result": 1, "data": {"video_list": [{
                "photo_id": "p1", "caption": "作品一", "create_time": 1786406400000,
                "view_count": 100, "like_count": 12, "comment_count": 3,
            }], "cursor": "next"}}
        return {"result": 1, "data": {"video_list": [{
            "photo_id": "p2", "caption": "作品二", "create_time": 1786492800000,
            "view_count": 200, "like_count": 20, "comment_count": 5,
        }], "cursor": ""}}

    monkeypatch.setitem(backend.__dict__, "_ks_official_get", fake_get)
    works = backend.kuaishou_official_list_works({}, 1, date(2026, 8, 10), date(2026, 8, 13), 10)

    assert [item["platformWorkId"] for item in works] == ["p1", "p2"]
    assert works[0]["metrics"] == {
        "views": 100, "likes": 12, "comments": 3, "shares": None,
        "followersGained": None, "avgWatchDurationSeconds": None, "completionRate": None,
    }
    assert calls[1]["cursor"] == "next"


def test_missing_official_auth_falls_back_but_rate_limit_does_not(monkeypatch):
    backend = create_backend_module()
    account = {"id": 7}
    fallback = [{"platformWorkId": "creator"}]
    monkeypatch.setitem(
        backend.__dict__, "kuaishou_official_list_works",
        lambda *_: (_ for _ in ()).throw(backend.KuaishouOfficialUnavailableError("missing")),
    )
    monkeypatch.setitem(backend.__dict__, "kuaishou_creator_list_works", lambda *_: fallback)
    assert backend._ksa_collect_works(account, 1, date.today(), date.today(), 20) == fallback

    called = []
    monkeypatch.setitem(
        backend.__dict__, "kuaishou_official_list_works",
        lambda *_: (_ for _ in ()).throw(backend.KuaishouAnalyticsStopError("limited")),
    )
    monkeypatch.setitem(backend.__dict__, "kuaishou_creator_list_works", lambda *_: called.append(True))
    with pytest.raises(backend.KuaishouAnalyticsStopError, match="limited"):
        backend._ksa_collect_works(account, 1, date.today(), date.today(), 20)
    assert called == []


def test_platform_and_comment_confirmation_are_hard_validated():
    backend = create_backend_module()
    with pytest.raises(ValueError, match="单个字符串 kuaishou"):
        backend._normalize_agent_tool_args("get_published_video_metrics", {"platform": ["kuaishou"], "publishRecordId": 1})
    with pytest.raises(ValueError, match="明确选择"):
        backend._run_agent_tool("get_published_video_comments", {
            "platform": "kuaishou", "publishRecordId": 1, "userConfirmed": False,
        })
    normalized = backend._normalize_agent_tool_args("list_account_video_metrics", {
        "platform": "kuaishou", "accountId": 1, "limit": 999,
    })
    assert normalized["limit"] == 100


def test_metric_text_parser_preserves_missing_values():
    backend = create_backend_module()
    metrics = backend._ks_metrics_from_text("播放 1.2万 点赞 320 评论 18 完播率 45%")
    assert metrics["views"] == 12000
    assert metrics["likes"] == 320
    assert metrics["comments"] == 18
    assert metrics["completionRate"] == 0.45
    assert metrics["shares"] is None


def test_public_errors_do_not_include_secret_values():
    backend = create_backend_module()
    message = backend._ks_public_error(RuntimeError("access_token=secret-value"), "request failed")
    assert "secret-value" not in message
    assert "RuntimeError" in message


def test_kuaishou_migration_contains_owner_scoped_snapshots_and_comment_deduplication():
    migration = Path("app/db/migrations/postgresql/V018__kuaishou_analytics.sql").read_text(encoding="utf-8")
    assert "account_id BIGINT REFERENCES user_info" in migration
    assert "platform_work_id TEXT" in migration
    assert "metrics JSONB" in migration
    assert "owner_user_id BIGINT NOT NULL" in migration
    assert "uq_platform_comment_sample" in migration
    assert "nickname" not in migration.lower()
    assert "avatar" not in migration.lower()


def test_derived_rates_are_zero_safe():
    backend = create_backend_module()
    empty = backend._ksa_derived({"metrics": {"views": 0, "likes": 2}, "publishedAt": datetime.now().isoformat()})
    assert empty["likeRate"] is None
    assert empty["engagementRate"] is None

    populated = backend._ksa_derived({
        "metrics": {"views": 100, "likes": 10, "comments": 2, "shares": 3},
        "publishedAt": datetime.now().isoformat(),
    })
    assert populated["viewsPerDay"] == pytest.approx(100, rel=0.01)
    assert populated["engagementRate"] == 0.15


def test_publish_binding_requires_one_exact_recent_match(monkeypatch):
    backend = create_backend_module()
    now = datetime.now()
    monkeypatch.setitem(backend.__dict__, "_ksa_collect_works", lambda *_: [
        {"platformWorkId": "matched", "title": "正文", "publishedAt": now, "pending": False},
        {"platformWorkId": "other", "title": "其他", "publishedAt": now, "pending": False},
    ])
    task = {
        "platformType": 4, "ownerUserId": 1, "accountId": 2, "accountFile": "account.json",
        "accountName": "测试号", "title": "标题", "description": "正文",
    }
    assert backend.confirm_kuaishou_published_work(task)["platformWorkId"] == "matched"

    monkeypatch.setitem(backend.__dict__, "_ksa_collect_works", lambda *_: [
        {"platformWorkId": "one", "title": "正文", "publishedAt": now, "pending": False},
        {"platformWorkId": "two", "title": "正文", "publishedAt": now, "pending": False},
    ])
    assert backend.confirm_kuaishou_published_work(task) is None


def test_react_loop_requires_skill_before_analytics(monkeypatch):
    backend = create_backend_module()
    actions = iter([
        {"type": "tool", "tool": "get_published_video_metrics", "args": {"platform": "kuaishou", "publishRecordId": 9}},
        {"type": "tool", "tool": "load_skill", "args": {"name": "kuaishou-analytics"}},
        {"type": "tool", "tool": "get_published_video_metrics", "args": {"platform": "kuaishou", "publishRecordId": 9}},
        {"type": "final", "answer": "完成"},
    ])
    monkeypatch.setitem(backend.__dict__, "_call_agent_contract", lambda *_args, **_kwargs: (next(actions), {}, {}))
    monkeypatch.setitem(backend.__dict__, "get_published_video_metrics", lambda *_: {"publishRecordId": 9})

    answer, results, _, _ = backend._run_react_loop("分析快手作品", {}, "session")

    assert answer == "完成"
    assert "必须先 load_skill" in results[0]["error"]
    assert results[1]["result"]["name"] == "kuaishou-analytics"
    assert results[2]["result"]["publishRecordId"] == 9
