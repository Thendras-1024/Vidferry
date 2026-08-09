"""工作流异常的稳定错误码与用户提示。"""

from __future__ import annotations

from app.core.errors import LLM_CATEGORY_ERROR_INFO


_WORKFLOW_ERROR_CONFIG = (
    (lambda exc, _text: exc.__class__.__name__ == "LLMContractError", "VF-LLM-CONTRACT-INVALID", "LLM_CONTRACT_ERROR", "模型输出未满足中文与结构化约束，系统已尝试修正但仍未通过。"),
    (lambda _exc, text: "AUDIO_EXTRACTION_FAILED:" in text, "VF-AUDIO-EXTRACTION-FAILED", "AUDIO_EXTRACTION_FAILED", "音频提取失败；请检查源视频音轨和 FFmpeg 配置。"),
    (lambda _exc, text: "RUNTIME_CONFIG_FAILED:WHISPER:" in text, "VF-ASR-RUNTIME-CONFIG", "ASR_RUNTIME_CONFIG", "Whisper 运行环境不可用；请按右上角消息中的配置指引修复后重试。"),
    (lambda _exc, text: "RUNTIME_CONFIG_FAILED:VIDEO_ENCODER:" in text, "VF-VIDEO-ENCODER-CONFIG", "VIDEO_ENCODER_CONFIG", "视频编码器不可用；请更新 NVIDIA 驱动以启用 NVENC，或将 VIDEO_ENCODER 改为 libx264 后重试。"),
    (lambda _exc, text: "ASR_TRANSCRIPTION_FAILED:WHISPER_MODEL_DOWNLOAD_FAILED" in text, "VF-ASR-MODEL-DOWNLOAD-FAILED", "ASR_MODEL_DOWNLOAD_FAILED", "Whisper 模型下载失败；请检查网络或 HF_ENDPOINT/HF_HOME 配置，也可在消息中复制预下载命令后重试。"),
    (lambda _exc, text: "ASR_TRANSCRIPTION_FAILED:CUDA_CUBLAS_12_MISSING" in text, "VF-ASR-CUDA-CUBLAS-MISSING", "ASR_CUDA_CUBLAS_MISSING", "Whisper GPU 转写无法加载 CUDA 12 cuBLAS（cublas64_12.dll）；请执行 GPU 环境安装，或改用 CPU 模式。"),
    (lambda _exc, text: "ASR_TRANSCRIPTION_FAILED:CUDA_CUDNN_MISSING" in text, "VF-ASR-CUDA-CUDNN-MISSING", "ASR_CUDA_CUDNN_MISSING", "Whisper GPU 转写无法加载 cuDNN；请执行 GPU 环境安装，或改用 CPU 模式。"),
    (lambda _exc, text: "ASR_TRANSCRIPTION_FAILED:" in text, "VF-ASR-TRANSCRIPTION-FAILED", "ASR_TRANSCRIPTION_FAILED", "语音识别失败；请检查 Whisper 模型、CPU / GPU 资源和源音频。"),
    (lambda _exc, text: "SUBTITLE_TRANSLATION_FAILED:" in text, "VF-SUBTITLE-TRANSLATION-FAILED", "SUBTITLE_TRANSLATION_FAILED", "字幕翻译失败；请检查网络和翻译服务后重试。"),
    (lambda _exc, text: "SUBTITLE_BURN_FAILED:" in text, "VF-SUBTITLE-BURN-FAILED", "SUBTITLE_BURN_FAILED", "字幕烧录失败；请检查 FFmpeg、磁盘空间和输出文件占用情况。"),
    (lambda _exc, text: "HIGHLIGHT_SEGMENTS_INSUFFICIENT:" in text, "VF-HIGHLIGHT-INSUFFICIENT", "HIGHLIGHT_SEGMENTS_INSUFFICIENT", "高光片段生成数量不足，任务未输出不完整成片；请重新生成剪辑方案后重试。"),
    (lambda _exc, text: "VF-PUBLISH-RATE-LIMIT" in text or "upload rate limit" in text.lower() or "code: 601" in text.lower(), "VF-PUBLISH-RATE-LIMIT", "PUBLISH_RATE_LIMIT", "平台限制该账号的上传频率；请等待一段时间后仅重发发布步骤，无需重新下载或处理视频。"),
    (lambda _exc, text: "PUBLISH_FAILED:" in text, "VF-PUBLISH-PLATFORM-FAILED", "PUBLISH_PLATFORM_FAILED", "平台发布失败；请检查所选账号状态、平台投稿限制和后端发布日志后重试。"),
    (lambda exc, _text: isinstance(exc, TimeoutError), "VF-WORKFLOW-TIMEOUT", "WORKFLOW_TIMEOUT", "任务执行超时，请稍后重试；如持续发生，请检查后端服务状态。"),
    (lambda exc, _text: isinstance(exc, FileNotFoundError), "VF-WORKFLOW-SOURCE-MISSING", "SOURCE_FILE_MISSING", "未找到任务所需文件，请先重新下载视频后再处理。"),
    (lambda exc, _text: isinstance(exc, PermissionError), "VF-WORKFLOW-FILE-PERMISSION", "FILE_PERMISSION_ERROR", "任务文件无法访问，请确认文件未被其他程序占用且目录可写。"),
    (lambda _exc, text: "未找到已下载视频文件" in text or "no such file" in text.lower(), "VF-WORKFLOW-SOURCE-MISSING", "SOURCE_FILE_MISSING", "未找到任务所需文件，请先重新下载视频后再处理。"),
    (lambda _exc, text: "未安装 yt-dlp" in text.lower(), "VF-DOWNLOAD-DEPENDENCY-MISSING", "DOWNLOAD_DEPENDENCY_MISSING", "下载组件未安装或不可用，请检查后端依赖配置。"),
    (lambda _exc, text: "ffmpeg 已执行，但未生成" in text.lower(), "VF-MEDIA-OUTPUT-MISSING", "MEDIA_OUTPUT_MISSING", "视频处理未生成有效输出文件，请重新处理；如持续发生，请检查磁盘空间和后端日志。"),
    (lambda _exc, text: "ffmpeg" in text.lower() or "cpb:" in text.lower(), "VF-MEDIA-PROCESS-UNCLASSIFIED", "MEDIA_PROCESS_UNCLASSIFIED", "视频处理失败，但工具输出未包含可判定原因。请查看任务编号对应的后端日志。"),
)


def classify_workflow_exception(exc):
    """返回可展示的工作流错误，不向前端透传命令行原始输出。"""
    category = getattr(exc, "category", None)
    if category in LLM_CATEGORY_ERROR_INFO:
        error_code, error_type, error_reason = LLM_CATEGORY_ERROR_INFO[category]
        return {
            "error_code": error_code,
            "error_type": error_type,
            "error_reason": error_reason,
            "error_detail": "",
        }
    text = str(exc or "")
    for matches, error_code, error_type, error_reason in _WORKFLOW_ERROR_CONFIG:
        if matches(exc, text):
            return {
                "error_code": error_code,
                "error_type": error_type,
                "error_reason": error_reason,
                "error_detail": "",
            }
    return {
        "error_code": "VF-WORKFLOW-UNCLASSIFIED",
        "error_type": "WORKFLOW_UNCLASSIFIED",
        "error_reason": "任务失败，但当前无法可靠判断原因。请查看任务编号对应的后端日志。",
        "error_detail": "",
    }
