"""Runtime loader for the modularized legacy backend.

The old backend was a single file with many cross-calling functions.  During the
modular transition we execute the split domain modules into one namespace so
routes and services keep their existing behavior while the source is no longer a
single monolith.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

MODULE_ORDER = [
    "app/backend/setup.py",
    "app/utils/backend_common.py",
    "app/db/schema.py",
    "app/core/youtube_service.py",
    "app/core/workflow.py",
    "app/core/youtube_download_service.py",
    "app/core/settings_service.py",
    "app/core/subtitle_service.py",
    "app/core/editing_service.py",
    "app/core/material_service.py",
    "app/core/workflow_runner.py",
    "app/core/youtube_search_service.py",
    "app/api/static.py",
    "app/api/upload.py",
    "app/api/youtube.py",
    "app/api/account.py",
    "app/api/login.py",
    "app/api/publish.py",
    "app/api/cookie.py",
    "app/utils/sse.py",
    "app/backend/shutdown.py",
]


def load_backend_namespace(target_globals: dict, repo_root: Path | None = None) -> dict:
    root = repo_root or Path(__file__).resolve().parents[2]
    target_globals.setdefault("__file__", str(root / "sau_backend.py"))
    target_globals.setdefault("__name__", "sau_backend")
    target_globals.setdefault("__package__", "")
    target_globals.setdefault("__builtins__", __builtins__)

    for relative_path in MODULE_ORDER:
        path = root / relative_path
        source = path.read_text(encoding="utf-8-sig")
        code = compile(source, str(path), "exec")
        exec(code, target_globals)
    return target_globals


def create_backend_module(name: str = "sau_backend") -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(Path(__file__).resolve().parents[2] / "sau_backend.py")
    load_backend_namespace(module.__dict__)
    return module
