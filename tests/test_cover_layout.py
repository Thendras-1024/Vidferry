import json

import pytest

import cv2
import numpy as np

from app.core import cover_service as cover


def _cover_file(monkeypatch):
    image = np.full((720, 1280, 3), 90, dtype=np.uint8)
    monkeypatch.setattr(cv2, "imread", lambda _path: image.copy())
    return "cover.jpg"


def test_rules_strategy_keeps_existing_layout_without_vision_call(tmp_path, monkeypatch):
    monkeypatch.setattr(cover, "_COVER_LAYOUT_STRATEGY", "rules")
    monkeypatch.setattr(cover, "_call_json_contract", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("不应调用视觉模型")))

    layout = cover.analyze_cover_layout(_cover_file(monkeypatch), 1280, 720, "第一行\n第二行")

    assert layout["source"] == "rules"
    assert layout["id"] in {"bottom_full", "top_full", "left_stack", "right_stack"}


def test_vision_strategy_uses_normalized_center_and_ass_coordinates(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(cover, "_COVER_LAYOUT_STRATEGY", "vision")
    monkeypatch.setattr(cover, "_get_llm_config_status", lambda: {"multimodal": {"ready": True, "visionReady": True}})

    def fake_call(**kwargs):
        captured.update(kwargs)
        return {"x": 0.5, "y": 0.5}, {}, {}

    monkeypatch.setattr(cover, "_call_json_contract", fake_call)
    layout = cover.analyze_cover_layout(_cover_file(monkeypatch), 1280, 720, "第一行\n第二行", signature="Vidferry")
    ass_file = tmp_path / "cover.ass"
    cover.write_cover_ass(ass_file, 1280, 720, 2, "第一行\n第二行", layout, signature="Vidferry")

    content = captured["messages"][0]["content"]
    prompt = content[0]["text"]
    assert captured["contract_id"] == "cover_layout_vision"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert '"width": 1280' in prompt and '"height": 720' in prompt
    assert layout["source"] == "vision"
    ass_text = ass_file.read_text(encoding="utf-8")
    assert any(f"\\pos({x}," in ass_text for x in range(638, 643))


def test_invalid_vision_result_falls_back_to_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(cover, "_COVER_LAYOUT_STRATEGY", "vision")
    monkeypatch.setattr(cover, "_get_llm_config_status", lambda: {"multimodal": {"ready": True, "visionReady": True}})
    monkeypatch.setattr(cover, "_call_json_contract", lambda **_kwargs: ({"x": 1.2, "y": 0.5}, {}, {}))

    layout = cover.analyze_cover_layout(_cover_file(monkeypatch), 1280, 720, "第一行\n第二行")

    assert layout["source"] == "rules_fallback"


@pytest.mark.parametrize(
    ("status", "result"),
    [
        ({"multimodal": {"ready": False, "visionReady": False}}, None),
        ({"multimodal": {"ready": True, "visionReady": True}}, TimeoutError("timeout")),
        ({"multimodal": {"ready": True, "visionReady": True}}, {"x": 0.5, "y": 0.5, "extra": True}),
    ],
)
def test_unavailable_or_invalid_vision_layout_falls_back_to_rules(tmp_path, monkeypatch, status, result):
    monkeypatch.setattr(cover, "_COVER_LAYOUT_STRATEGY", "vision")
    monkeypatch.setattr(cover, "_get_llm_config_status", lambda: status)
    if isinstance(result, Exception):
        monkeypatch.setattr(cover, "_call_json_contract", lambda **_kwargs: (_ for _ in ()).throw(result))
    elif result is not None:
        monkeypatch.setattr(cover, "_call_json_contract", lambda **kwargs: (kwargs["validator"](result), {}, {}))

    layout = cover.analyze_cover_layout(_cover_file(monkeypatch), 1280, 720, "第一行\n第二行")

    assert layout["source"] == "rules_fallback"


def test_face_overlap_rejects_vision_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(cover, "_COVER_LAYOUT_STRATEGY", "vision")
    monkeypatch.setattr(cover, "_get_llm_config_status", lambda: {"multimodal": {"ready": True, "visionReady": True}})
    monkeypatch.setattr(cover, "_call_json_contract", lambda **_kwargs: ({"x": 0.5, "y": 0.5}, {}, {}))
    original_masks = cover._cover_visual_masks

    def masks_with_face(canvas, width, height):
        gray, edges, face_mask, text_mask = original_masks(canvas, width, height)
        face_mask[200:520, 320:960] = 255
        return gray, edges, face_mask, text_mask

    monkeypatch.setattr(cover, "_cover_visual_masks", masks_with_face)
    layout = cover.analyze_cover_layout(_cover_file(monkeypatch), 1280, 720, "第一行\n第二行")

    assert layout["source"] == "rules_fallback"


def test_vision_center_contract_rejects_extra_fields_and_out_of_bounds_values():
    for payload in ({"x": 0.5}, {"x": 0.5, "y": 0.5, "reason": "extra"}, {"x": 0, "y": 0.5}):
        try:
            cover._validate_vision_center(json.loads(json.dumps(payload)))
        except ValueError:
            continue
        raise AssertionError("应拒绝不合法的视觉模型坐标")
