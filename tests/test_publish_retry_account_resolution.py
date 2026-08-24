from app.backend.runtime import create_backend_module


def test_retry_uses_account_id_after_relogin_rotates_cookie_file():
    backend = create_backend_module("test_publish_retry_account_resolution_backend")
    calls = []

    class Cursor:
        def execute(self, sql, params):
            calls.append((sql, params))

        def fetchone(self):
            return {"id": 4, "status": 1, "filePath": "tencent_current.json"}

    account = backend._retry_publish_account(
        Cursor(),
        {"platformType": 2, "accountId": 4, "accountFile": "tencent_expired.json"},
        1,
    )

    assert account["filePath"] == "tencent_current.json"
    assert len(calls) == 1
    assert "WHERE id = %s" in calls[0][0]
    assert calls[0][1] == (4, 2, 1)
