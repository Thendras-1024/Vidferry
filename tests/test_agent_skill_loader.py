from pathlib import Path

import pytest

from app.backend.runtime import create_backend_module


def _skill(root, folder, name, description="测试 Skill", body="仅在按需加载后可见"):
    skill_dir = root / "skills" / folder
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


def test_skill_metadata_is_injected_without_body(tmp_path):
    backend = create_backend_module()
    _skill(tmp_path, "sample", "sample", body="BODY_MUST_NOT_BE_EAGERLY_INJECTED")
    backend.BASE_DIR = tmp_path

    catalog = backend.list_agent_skills()
    prompt = backend._build_react_messages("测试", {}, [])[1]["content"]

    assert catalog == [{"name": "sample", "description": "测试 Skill"}]
    assert "BODY_MUST_NOT_BE_EAGERLY_INJECTED" not in prompt
    assert backend.load_skill("sample")["instructions"] == "BODY_MUST_NOT_BE_EAGERLY_INJECTED"


def test_skill_reference_is_limited_to_direct_markdown(tmp_path):
    backend = create_backend_module()
    skill_dir = _skill(tmp_path, "sample", "sample")
    references = skill_dir / "references"
    references.mkdir()
    (references / "metrics.md").write_text("metrics", encoding="utf-8")
    backend.BASE_DIR = tmp_path

    assert backend.read_skill_reference("sample", "references/metrics.md")["content"] == "metrics"
    for path in ("../secret.md", "references/../SKILL.md", "SKILL.md", "references/data.json"):
        with pytest.raises(backend.AgentSkillError):
            backend.read_skill_reference("sample", path)


def test_skill_scan_rejects_duplicate_names_and_oversized_files(tmp_path):
    backend = create_backend_module()
    _skill(tmp_path, "first", "duplicate")
    _skill(tmp_path, "second", "duplicate")
    backend.BASE_DIR = tmp_path
    with pytest.raises(backend.AgentSkillError, match="重复"):
        backend.list_agent_skills()

    other_root = tmp_path / "large"
    skill_dir = _skill(other_root, "large", "large")
    (skill_dir / "SKILL.md").write_text("x" * (128 * 1024 + 1), encoding="utf-8")
    backend.BASE_DIR = other_root
    with pytest.raises(backend.AgentSkillError, match="超过"):
        backend.list_agent_skills()


def test_skill_name_and_root_boundary_are_validated(tmp_path):
    backend = create_backend_module()
    _skill(tmp_path, "invalid", "../invalid")
    backend.BASE_DIR = tmp_path
    with pytest.raises(backend.AgentSkillError, match="格式无效"):
        backend.list_agent_skills()
