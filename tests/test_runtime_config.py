import subprocess

from app.core import runtime_config


def _prepare_cuda_status(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "small")
    monkeypatch.setenv("WHISPER_DEVICE", "cuda")
    monkeypatch.setenv("WHISPER_COMPUTE_TYPE", "int8_float16")
    monkeypatch.setattr(runtime_config.Path, "exists", lambda _path: False)
    monkeypatch.setattr(runtime_config, "_WHISPER_STATUS_CACHE", {})
    monkeypatch.setattr(runtime_config, "time", type("Clock", (), {"monotonic": staticmethod(lambda: 100.0)}))


def test_whisper_cuda_probe_uses_thirty_second_timeout_and_caches(monkeypatch):
    _prepare_cuda_status(monkeypatch)
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(args[0], 0, stdout="1\n", stderr="")

    monkeypatch.setattr(runtime_config.subprocess, "run", fake_run)

    first = runtime_config._whisper_status()
    second = runtime_config._whisper_status()

    assert first["ready"] is True
    assert second == first
    assert len(calls) == 1
    assert calls[0]["timeout"] == 30


def test_whisper_cuda_probe_timeout_has_specific_message(monkeypatch):
    _prepare_cuda_status(monkeypatch)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(runtime_config.subprocess, "run", fake_run)

    status = runtime_config._whisper_status()

    assert status["ready"] is False
    assert "初始化检测超时" in status["message"]
    assert "30 秒" in status["message"]


def test_whisper_cuda_probe_rejects_missing_device_or_process_failure(monkeypatch):
    _prepare_cuda_status(monkeypatch)

    for result in (
        subprocess.CompletedProcess([], 0, stdout="0\n", stderr=""),
        subprocess.CompletedProcess([], 1, stdout="", stderr="CUDA failed"),
    ):
        monkeypatch.setattr(runtime_config, "_WHISPER_STATUS_CACHE", {})
        monkeypatch.setattr(runtime_config.subprocess, "run", lambda *args, result=result, **kwargs: result)

        status = runtime_config._whisper_status()

        assert status["ready"] is False
        assert "CUDA 不可用" in status["message"]


def test_whisper_cpu_status_does_not_probe_cuda(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "small")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("WHISPER_COMPUTE_TYPE", "int8")
    monkeypatch.setattr(runtime_config.Path, "exists", lambda _path: False)
    monkeypatch.setattr(runtime_config, "_WHISPER_STATUS_CACHE", {})
    monkeypatch.setattr(runtime_config.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CPU must not probe CUDA")))
    monkeypatch.setattr(runtime_config, "time", type("Clock", (), {"monotonic": staticmethod(lambda: 100.0)}))
    monkeypatch.setattr("faster_whisper.utils.available_models", lambda: ["small"])
    monkeypatch.setattr("huggingface_hub.try_to_load_from_cache", lambda *args, **kwargs: object())

    assert runtime_config._whisper_status()["ready"] is True
