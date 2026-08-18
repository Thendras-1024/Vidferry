"""Agent skill 元数据扫描与受限按需读取。"""

from __future__ import annotations

import re as _skill_re
from pathlib import Path as _SkillPath


_AGENT_SKILL_NAME_RE = _skill_re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_AGENT_SKILL_MAX_BYTES = 128 * 1024
_AGENT_SKILL_REFERENCE_MAX_BYTES = 128 * 1024


class AgentSkillError(ValueError):
    pass


def _agent_skills_root():
    return (_SkillPath(BASE_DIR) / "skills").resolve()


def _read_limited_utf8(path, max_bytes):
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise AgentSkillError(f"Skill 文件不可读取: {path.name}") from exc
    if size > max_bytes:
        raise AgentSkillError(f"Skill 文件超过 {max_bytes} 字节限制: {path.name}")
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AgentSkillError(f"Skill 文件必须使用 UTF-8: {path.name}") from exc


def _parse_agent_skill_document(path):
    text = _read_limited_utf8(path, _AGENT_SKILL_MAX_BYTES)
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AgentSkillError(f"Skill 缺少 YAML frontmatter: {path.name}")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise AgentSkillError(f"Skill frontmatter 未闭合: {path.name}") from exc
    metadata = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise AgentSkillError(f"Skill frontmatter 字段无效: {path.name}")
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"\'')
    name = metadata.get("name", "")
    description = metadata.get("description", "")
    if not _AGENT_SKILL_NAME_RE.fullmatch(name):
        raise AgentSkillError(f"Skill name 格式无效: {name or path.parent.name}")
    if not description:
        raise AgentSkillError(f"Skill description 不能为空: {name}")
    body = "\n".join(lines[end + 1:]).strip()
    return {"name": name, "description": description, "body": body, "text": text}


def _scan_agent_skills():
    root = _agent_skills_root()
    if not root.is_dir():
        return {}
    catalog = {}
    for skill_file in sorted(root.glob("*/SKILL.md")):
        resolved = skill_file.resolve()
        if not resolved.is_relative_to(root):
            raise AgentSkillError("Skill 路径越过 skills 目录边界")
        item = _parse_agent_skill_document(resolved)
        if item["name"] in catalog:
            raise AgentSkillError(f"Skill name 重复: {item['name']}")
        catalog[item["name"]] = {**item, "dir": resolved.parent}
    return catalog


def list_agent_skills():
    return [
        {"name": item["name"], "description": item["description"]}
        for item in _scan_agent_skills().values()
    ]


def load_skill(name):
    name = str(name or "").strip()
    if not _AGENT_SKILL_NAME_RE.fullmatch(name):
        raise AgentSkillError("Skill name 格式无效")
    item = _scan_agent_skills().get(name)
    if not item:
        raise AgentSkillError(f"Skill 不存在: {name}")
    return {"name": name, "description": item["description"], "instructions": item["body"]}


def read_skill_reference(name, path):
    name = str(name or "").strip()
    relative = _SkillPath(str(path or ""))
    if relative.is_absolute() or len(relative.parts) != 2 or relative.parts[0] != "references":
        raise AgentSkillError("只允许读取 references/*.md")
    if relative.suffix.lower() != ".md" or any(part in {"", ".", ".."} for part in relative.parts):
        raise AgentSkillError("Skill reference 路径无效")
    item = _scan_agent_skills().get(name)
    if not item:
        raise AgentSkillError(f"Skill 不存在: {name}")
    target = (item["dir"] / relative).resolve()
    reference_root = (item["dir"] / "references").resolve()
    if not target.is_relative_to(reference_root) or not target.is_file():
        raise AgentSkillError("Skill reference 不存在或越过目录边界")
    return {"name": name, "path": relative.as_posix(), "content": _read_limited_utf8(target, _AGENT_SKILL_REFERENCE_MAX_BYTES)}
