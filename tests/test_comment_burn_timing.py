from app.core.comment_burn_service import _normalized_comment_selected_limit, schedule_comment_burn
from app.backend.runtime import create_backend_module


def test_comment_schedule_uses_source_timeline_and_ten_second_gap():
    snapshot = {"status": "ready", "comments": [{"id": str(index)} for index in range(50)]}

    scheduled = schedule_comment_burn(snapshot, 100, 50)

    assert [(item["displayStart"], item["displayEnd"]) for item in scheduled["comments"]] == [
        (25, 43), (53, 71), (81, 99),
    ]
    assert _normalized_comment_selected_limit(50) == 50
    assert _normalized_comment_selected_limit("invalid") == 30


def test_comment_ass_uses_two_second_entrance_and_four_sevenths_width():
    backend = create_backend_module()
    layout = backend._comment_burn_layout({"width": 1400, "height": 900})
    lines = []

    backend._append_comment_burn_ass(lines, [{
        "id": "one", "author": "tester", "text": "A useful English comment.",
        "displayStart": 25, "displayEnd": 36,
    }], {"width": 1400, "height": 900})

    assert layout["textWidth"] == 800
    assert any(r"\fad(2000,1000)" in line and r"\move(" in line and ",0,2000)" in line for line in lines)


def test_comment_avatar_uses_matching_entrance_and_exit_fades(tmp_path):
    backend = create_backend_module()
    avatar = tmp_path / "avatar.png"
    avatar.write_bytes(b"placeholder")

    filters, _ = backend._comment_avatar_filter_complex(
        tmp_path / "comments.ass", [], [{"path": str(avatar), "start": 25, "end": 36}], {"width": 1080, "height": 1920},
    )

    assert "fade=t=in:st=0:d=2" in filters
    assert "fade=t=out:st=10.00:d=1" in filters
    assert "lt(t\\,27.00)" in filters


def test_highlight_ass_excludes_comment_styles_and_dialogues(tmp_path):
    backend = create_backend_module()
    source = tmp_path / "source.ass"
    output = tmp_path / "highlight.ass"
    source.write_text(
        "[V4+ Styles]\nStyle: CommentMeta,Arial,20\nStyle: Subtitle,Arial,20\n"
        "[Events]\nDialogue: 0,0:00:25.00,0:00:36.00,CommentMeta,,0,0,0,,comment\n"
        "Dialogue: 0,0:00:25.00,0:00:36.00,Subtitle,,0,0,0,,subtitle\n",
        encoding="utf-8",
    )

    backend._write_clip_ass(source, output, 20, 40, include_comments=False)
    rendered = output.read_text(encoding="utf-8")

    assert "CommentMeta" not in rendered
    assert "subtitle" in rendered
