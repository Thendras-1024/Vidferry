from app.backend.runtime import create_backend_module


def test_highlight_shortfall_is_a_warning_instead_of_a_failure():
    backend = create_backend_module()

    warning = backend._highlight_shortfall_message(
        {"highlightIntroEnabled": True, "highlightCount": 3},
        {"segments": [{"path": "segment.mp4"}]},
    )

    assert warning == "高光片段数量不足：请求 3 条，实际生成 1 条，已使用现有片段继续生成成片"
    assert backend._highlight_shortfall_message(
        {"highlightIntroEnabled": False, "highlightCount": 3},
        {"segments": []},
    ) == ""
