"""Public .env runtime checks used by the status API and task guards."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.config import VIDEO_ENCODER
from app.utils.ffmpeg_util import _resolve_ffmpeg_command


class RuntimeConfigError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"RUNTIME_CONFIG_FAILED:{code}:{message}")


def _status(ready, message="", *, level="info", action_value="", effective=None):
    return {
        "ready": bool(ready), "level": level, "message": message,
        "actionValue": action_value, "effective": effective or {},
    }


def _whisper_status():
    model = str(os.environ.get("WHISPER_MODEL_SIZE", "small") or "small").strip()
    device = str(os.environ.get("WHISPER_DEVICE", "cpu") or "cpu").strip().lower()
    compute_type = str(os.environ.get("WHISPER_COMPUTE_TYPE", "int8") or "int8").strip().lower()
    effective = {"model": "large-v3" if model == "large" else model, "device": device, "computeType": compute_type}
    if device not in {"cpu", "cuda", "auto"}:
        return _status(False, "WHISPER_DEVICE 仅支持 cpu、cuda 或 auto。", level="error", effective=effective)
    allowed_compute_types = {
        "cpu": {"int8", "int8_float32", "float32"},
        "cuda": {"float16", "int8_float16", "int8", "float32", "bfloat16", "int8_bfloat16", "int8_float32"},
    }
    if device in allowed_compute_types and compute_type not in allowed_compute_types[device]:
        return _status(False, f"WHISPER_COMPUTE_TYPE={compute_type} 不支持 {device}。", level="error", effective=effective)
    if Path(model).exists():
        if not Path(model).is_dir():
            return _status(False, "WHISPER_MODEL_SIZE 指向的本地模型路径不是目录。", level="error", effective=effective)
        return _status(True, effective=effective)
    try:
        from faster_whisper.utils import available_models
        if model not in available_models():
            return _status(False, "WHISPER_MODEL_SIZE 无效；请使用 faster-whisper 支持的模型名或本地模型目录。", level="error", effective=effective)
        from huggingface_hub import try_to_load_from_cache
        repo = "Systran/faster-whisper-large-v3" if model == "large" else f"Systran/faster-whisper-{model}"
        cached = try_to_load_from_cache(repo, "model.bin")
    except ImportError:
        return _status(False, "未安装 faster-whisper；请重新安装后端依赖。", level="error", effective=effective)
    except Exception as exc:
        return _status(False, f"无法检查 Whisper 模型缓存：{exc}", level="warning", effective=effective)
    if not cached:
        command = f'python -c "from faster_whisper import download_model; download_model(\'{effective["model"]}\')"'
        return _status(True, "Whisper 模型尚未缓存，将在首次转写时自动下载。", level="warning", action_value=command, effective=effective)
    if device == "cuda":
        try:
            probe = subprocess.run(
                [os.sys.executable, "-c", "import ctranslate2; print(ctranslate2.get_cuda_device_count())"],
                capture_output=True, text=True, timeout=5,
            )
            if probe.returncode != 0 or int((probe.stdout or "0").strip() or 0) < 1:
                raise RuntimeError((probe.stderr or probe.stdout or "未检测到 CUDA 设备").strip())
        except Exception as exc:
            return _status(False, "Whisper CUDA 不可用；请执行 conda env update -n vidferry -f environment.gpu-win.yml 后重启，或改为 WHISPER_DEVICE=cpu。", level="error", action_value="conda env update -n vidferry -f environment.gpu-win.yml", effective=effective)
    return _status(True, effective=effective)


def _encoder_status():
    effective = {"encoder": VIDEO_ENCODER}
    if VIDEO_ENCODER not in {"libx264", "h264_nvenc"}:
        return _status(False, "VIDEO_ENCODER 仅支持 libx264 或 h264_nvenc。", level="error", effective=effective)
    try:
        ffmpeg = _resolve_ffmpeg_command()
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=16x16:d=0.04", "-frames:v", "1", "-c:v", VIDEO_ENCODER, "-f", "null", "-"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode:
            raise RuntimeError((result.stderr or "FFmpeg 编码测试失败").strip()[:300])
    except Exception as exc:
        if VIDEO_ENCODER == "h264_nvenc":
            message = "h264_nvenc 不可用；请安装兼容的 NVIDIA 驱动和支持 NVENC 的 FFmpeg，或改为 VIDEO_ENCODER=libx264。"
        else:
            message = f"libx264 不可用；请检查 FFmpeg 安装。{exc}"
        return _status(False, message, level="error", effective=effective)
    return _status(True, effective=effective)


def get_runtime_config_status():
    return {"whisper": _whisper_status(), "videoEncoder": _encoder_status()}


def ensure_whisper_runtime_ready():
    status = _whisper_status()
    if not status["ready"]:
        raise RuntimeConfigError("WHISPER", status["message"])


def ensure_video_encoder_ready():
    status = _encoder_status()
    if not status["ready"]:
        raise RuntimeConfigError("VIDEO_ENCODER", status["message"])
