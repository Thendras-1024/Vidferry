"""评测清单、运行元数据与可恢复结果文件。"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .metrics import SCHEMA_VERSION, SUPPORTED_LANGUAGES


EVALUATION_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = EVALUATION_ROOT.parent
DEFAULT_MANIFEST_ROOT = EVALUATION_ROOT / "manifests" / "v1"
DEFAULT_RESULT_ROOT = EVALUATION_ROOT / "results"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def json_dumps(value, *, indent=None):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent, default=str)


def load_jsonl(path):
    path = Path(path)
    rows = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL 格式错误 : file = {path} | line = {line_number} | reason = {exc.msg}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL 行必须是对象 : file = {path} | line = {line_number}")
            rows.append(value)
    return rows


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as target:
        for row in rows:
            target.write(json_dumps(row) + "\n")
    temporary.replace(path)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json_dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as target:
        target.write(json_dumps(row) + "\n")
        target.flush()
        os.fsync(target.fileno())


def manifest_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_manifest(cases, suite, *, system=""):
    errors, seen = [], set()
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("id") or "").strip()
        prefix = f"line = {index} | case_id = {case_id or '-'}"
        if not case_id:
            errors.append(f"{prefix} | missing = id")
        elif case_id in seen:
            errors.append(f"{prefix} | duplicate = id")
        seen.add(case_id)
        if case.get("schemaVersion") != SCHEMA_VERSION:
            errors.append(f"{prefix} | schemaVersion must be {SCHEMA_VERSION}")
        if case.get("status") != "ready":
            errors.append(f"{prefix} | status must be ready")
        language = str(case.get("language") or "")
        if suite in {"asr", "translation"} and language not in SUPPORTED_LANGUAGES:
            errors.append(f"{prefix} | unsupported language = {language or '-'}")
        if suite == "asr":
            if not str(case.get("reference") or "").strip():
                errors.append(f"{prefix} | missing = reference")
            media = Path(str(case.get("media") or ""))
            if not str(case.get("media") or "").strip():
                errors.append(f"{prefix} | missing = media")
            elif media.is_absolute():
                errors.append(f"{prefix} | media must be project-relative")
            elif system != "replay" and not (PROJECT_ROOT / media).is_file():
                errors.append(f"{prefix} | media not found = {media}")
        elif suite == "translation":
            if not str(case.get("source") or "").strip():
                errors.append(f"{prefix} | missing = source")
            if not any(str(item).strip() for item in (case.get("references") or [])):
                errors.append(f"{prefix} | missing = references")
            if system == "review" and not str(case.get("initialTranslation") or "").strip():
                errors.append(f"{prefix} | missing = initialTranslation")
        elif suite == "agent":
            if not str(case.get("message") or "").strip():
                errors.append(f"{prefix} | missing = message")
            if not isinstance(case.get("expected"), dict):
                errors.append(f"{prefix} | missing = expected")
            else:
                expected = case["expected"]
                if expected.get("intent") is not None and not str(expected.get("intent") or "").strip():
                    errors.append(f"{prefix} | expected.intent must be non-empty string")
                for key in ("requiredTools", "allowedTools", "forbiddenTools", "requiredSkills", "allowedSkills"):
                    if key in expected and not isinstance(expected[key], list):
                        errors.append(f"{prefix} | expected.{key} must be array")
                if "expectedState" in expected and not isinstance(expected["expectedState"], dict):
                    errors.append(f"{prefix} | expected.expectedState must be object")
            if not isinstance(case.get("frozenTools", {}), dict):
                errors.append(f"{prefix} | frozenTools must be object")
        else:
            errors.append(f"unsupported suite = {suite}")
            break
    return errors


def _git_output(*args):
    try:
        return subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def git_metadata():
    status = _git_output("status", "--porcelain")
    digest = hashlib.sha256()
    try:
        diff = subprocess.run(["git", "diff", "--binary"], cwd=PROJECT_ROOT, check=True, capture_output=True).stdout
        digest.update(diff)
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        for raw_path in sorted(item for item in untracked if item):
            path = PROJECT_ROOT / os.fsdecode(raw_path)
            if path.is_file():
                digest.update(raw_path)
                digest.update(path.read_bytes())
    except (OSError, subprocess.CalledProcessError):
        digest = hashlib.sha256()
    return {
        "commit": _git_output("rev-parse", "HEAD"),
        "branch": _git_output("branch", "--show-current"),
        "dirty": bool(status),
        "worktreeHash": digest.hexdigest() if status else "",
    }


def hardware_metadata():
    result = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
    }
    try:
        import torch

        result.update({"torch": torch.__version__, "cuda": torch.version.cuda or "", "cudaAvailable": torch.cuda.is_available()})
        if torch.cuda.is_available():
            result["gpu"] = torch.cuda.get_device_name(0)
    except ImportError:
        result["torch"] = ""
        result["cudaAvailable"] = False
    return result


def safe_run_directory(run_id, result_root=DEFAULT_RESULT_ROOT, *, resume=False):
    if not _RUN_ID_PATTERN.fullmatch(str(run_id or "")):
        raise ValueError("run-id 仅允许字母、数字、点、下划线和连字符，长度不超过 80。")
    path = Path(result_root) / run_id
    if path.exists() and not resume:
        raise FileExistsError(f"评测结果目录已存在 : run_id = {run_id} | 使用 --resume 继续")
    path.mkdir(parents=True, exist_ok=True)
    return path


def existing_success_keys(raw_path):
    if not Path(raw_path).is_file():
        return set()
    return {
        (row.get("id"), int(row.get("trial") or 1))
        for row in load_jsonl(raw_path)
        if row.get("status") == "success"
    }


def run_metadata(*, run_id, suite, system, manifest, command):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "suite": suite,
        "system": system,
        "datasetVersion": Path(manifest).parent.name,
        "manifest": str(Path(manifest).resolve().relative_to(PROJECT_ROOT)) if Path(manifest).resolve().is_relative_to(PROJECT_ROOT) else str(Path(manifest).resolve()),
        "manifestHash": manifest_hash(manifest),
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "command": list(command),
        "git": git_metadata(),
        "hardware": hardware_metadata(),
        "executable": sys.executable,
    }
