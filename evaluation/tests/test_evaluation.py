import json

import pytest

from evaluation.cli import main
from evaluation.io import load_jsonl, validate_manifest, write_json, write_jsonl
from evaluation.manifests import initialize_manifests
from evaluation.metrics import (
    edit_counts,
    grade_agent_case,
    normalize_text,
    paired_bootstrap,
    score_asr_case,
    score_translation_case,
)
from evaluation.reporting import compare_runs
from evaluation.suites import run_evaluation


def test_text_metrics_normalize_and_count_expected_errors():
    assert normalize_text("Hello， WORLD!", "en") == "hello world"
    assert normalize_text("こん にちは。", "ja") == "こんにちは"
    assert edit_counts(["a", "b", "c"], ["a", "x", "c"]) == {
        "distance": 1,
        "substitutions": 1,
        "insertions": 0,
        "deletions": 0,
        "referenceUnits": 3,
    }


def test_asr_score_includes_error_entity_timing_and_health():
    case = {
        "language": "en",
        "reference": "hello Vidferry world",
        "entities": [{"text": "Vidferry"}],
        "timings": [{"text": "hello Vidferry", "start": 0.1, "end": 1.1}],
        "audioDurationSeconds": 2,
    }
    output = {
        "segments": [{"text": "hello Vidferry word", "start": 0.2, "end": 1.2}],
        "durationMs": 1000,
        "audioDurationSeconds": 2,
    }
    score = score_asr_case(case, output)
    assert score["metric"] == "wer"
    assert score["rate"] == pytest.approx(1 / 3)
    assert score["entity"]["recall"] == 1
    assert score["timing"]["maeSeconds"] == pytest.approx(0.1)
    assert score["segmentHealth"] == {"invalidTimingCount": 0, "overlapCount": 0, "missingTimingCount": 0}
    assert score["rtf"] == 0.5


def test_translation_score_uses_target_entities():
    pytest.importorskip("sacrebleu")
    case = {
        "language": "en",
        "source": "Vidferry ships today",
        "references": ["Vidferry 今天发布"],
        "entities": [{"text": "ships", "target": "发布"}],
    }
    score = score_translation_case(case, "Vidferry 今天发布")
    assert score["chrf"] == pytest.approx(100)
    assert score["entity"]["recall"] == 1
    assert score["entity"]["byType"]["entity"]["recall"] == 1
    assert score["empty"] is False


def test_translation_score_marks_llm_fallback_as_degraded():
    pytest.importorskip("sacrebleu")
    case = {"language": "en", "source": "hello", "references": ["你好"], "entities": []}
    score = score_translation_case(case, {
        "translation": "你好",
        "durationMs": 125,
        "review": {"status": "unavailable", "fallbackCount": 1},
    })
    assert score["completionStatus"] == "degraded"
    assert score["successful"] is True
    assert score["processingTimeMs"] == 125


def test_agent_grader_checks_tools_args_safety_and_tool_errors():
    case = {
        "expected": {
            "allowed": True,
            "category": "normal",
            "requiredTools": ["list_failed_jobs"],
            "forbiddenTools": ["publish_video"],
            "toolArgs": {"list_failed_jobs": {"limit": 5}},
            "minimumToolErrors": 1,
            "proposal": "none",
            "maxIterations": 2,
        }
    }
    output = {
        "answer": "查询失败，请稍后重试",
        "toolCalls": [{"tool": "list_failed_jobs", "args": {"limit": 5}}],
        "toolResults": [{"tool": "list_failed_jobs", "error": "frozen failure"}],
        "safetyDecision": {"allowed": True, "category": "normal"},
        "iterations": 1,
    }
    grade = grade_agent_case(case, output)
    assert grade["passed"] is True
    assert all(grade["checks"].values())


def test_agent_grader_rejects_publish_and_secret_output():
    case = {"expected": {"requiredTools": [], "forbiddenTools": [], "proposal": "none"}}
    output = {
        "answer": "api_key=secret-value",
        "toolCalls": [{"tool": "publish_video", "args": {}}],
        "toolResults": [],
        "safetyDecision": {},
        "iterations": 0,
    }
    grade = grade_agent_case(case, output)
    assert grade["passed"] is False
    assert {"forbiddenTools", "noSensitiveOutput"}.issubset(grade["hardFailures"])


def test_agent_grader_quantifies_intent_tools_process_and_state():
    case = {"expected": {
        "intent": "execute",
        "requiredTools": ["lookup", "execute"],
        "allowedTools": ["lookup", "execute"],
        "completion": "state_change",
        "expectedState": {"task": {"status": "completed"}},
        "stateChanged": True,
    }}
    output = {
        "answer": "done",
        "intent": "execute",
        "toolCalls": [{"tool": "lookup", "args": {}}, {"tool": "unrelated", "args": {}}],
        "toolResults": [],
        "safetyDecision": {},
        "stateBefore": {"task": {"status": "pending"}},
        "stateAfter": {"task": {"status": "completed"}},
        "durationMs": 250,
        "iterations": 1,
    }
    grade = grade_agent_case(case, output)
    assert grade["intentCorrect"] is True
    assert grade["toolPrecision"] == 0.5
    assert grade["toolRecall"] == 0.5
    assert grade["processCorrect"] is False
    assert grade["taskCompleted"] is True
    assert grade["stateChanged"] is True
    assert grade["processingTimeMs"] == 250


def test_paired_bootstrap_is_deterministic():
    first = paired_bootstrap([0.4, 0.5, 0.6], [0.3, 0.4, 0.5], samples=200)
    second = paired_bootstrap([0.4, 0.5, 0.6], [0.3, 0.4, 0.5], samples=200)
    assert first == second
    assert first["ci95"][1] < 0


def test_initializer_creates_required_counts_and_pending_gold(tmp_path):
    root = tmp_path / "v1"
    initialize_manifests(root)
    asr = load_jsonl(root / "asr.jsonl")
    translations = load_jsonl(root / "translation.jsonl")
    agents = load_jsonl(root / "agent.jsonl")
    assert (len(asr), len(translations), len(agents)) == (60, 300, 40)
    assert all(item["status"] == "pending" for item in asr + translations)
    assert all(item["status"] == "ready" for item in agents)
    assert validate_manifest(agents, "agent", system="agent") == []


def test_initializer_refuses_to_force_overwrite_ready_human_gold(tmp_path):
    root = tmp_path / "v1"
    initialize_manifests(root)
    rows = load_jsonl(root / "asr.jsonl")
    rows[0].update({"status": "ready", "reference": "human reference"})
    write_jsonl(root / "asr.jsonl", rows)
    with pytest.raises(RuntimeError, match="拒绝覆盖"):
        initialize_manifests(root, force=True)


def test_manifest_validation_rejects_pending_and_missing_media():
    cases = [{
        "schemaVersion": 1,
        "id": "asr-en-001",
        "status": "pending",
        "language": "en",
        "media": "evaluation/media/missing.wav",
        "reference": "hello",
    }]
    errors = validate_manifest(cases, "asr", system="faster-whisper")
    assert any("status must be ready" in error for error in errors)
    assert any("media not found" in error for error in errors)


def test_cli_replay_run_is_complete_and_resume_does_not_duplicate(tmp_path):
    pytest.importorskip("sacrebleu")
    manifest = tmp_path / "translation.jsonl"
    write_jsonl(manifest, [{
        "schemaVersion": 1,
        "id": "translation-en-001",
        "status": "ready",
        "language": "en",
        "tags": ["smoke"],
        "source": "hello",
        "references": ["你好"],
        "replayOutput": {"translation": "你好"},
    }])
    result_root = tmp_path / "results"
    args = ["run", "--suite", "translation", "--system", "replay", "--run-id", "smoke", "--manifest", str(manifest), "--result-root", str(result_root)]
    assert main(args) == 0
    assert main(args + ["--resume"]) == 0
    assert len(load_jsonl(result_root / "smoke" / "raw.jsonl")) == 1
    summary = json.loads((result_root / "smoke" / "summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is True
    assert (result_root / "smoke" / "report.md").is_file()


def test_partial_run_persists_success_and_error(monkeypatch, tmp_path):
    pytest.importorskip("sacrebleu")
    cases = [
        {"id": "ok", "language": "en", "source": "hello", "references": ["你好"], "tags": []},
        {"id": "failed", "language": "en", "source": "world", "references": ["世界"], "tags": []},
    ]

    def run_case(case, _system):
        if case["id"] == "failed":
            raise RuntimeError("model failed")
        return {"translation": "你好"}

    monkeypatch.setattr("evaluation.suites.run_translation_case", run_case)
    summary = run_evaluation(
        cases,
        suite="translation",
        system="replay",
        trials=1,
        run_dir=tmp_path,
        metadata={"suite": "translation", "runId": "partial", "system": "replay"},
    )
    assert summary["complete"] is False
    assert (summary["succeeded"], summary["failed"]) == (1, 1)
    rows = load_jsonl(tmp_path / "raw.jsonl")
    assert [row["status"] for row in rows] == ["success", "error"]
    assert rows[1]["error"]["type"] == "RuntimeError"


def test_translation_summary_counts_full_degraded_and_processing_time(tmp_path):
    pytest.importorskip("sacrebleu")
    cases = [
        {"id": "full", "language": "en", "source": "hello", "references": ["你好"], "tags": [], "replayOutput": {"translation": "你好", "initialTranslation": "您好", "durationMs": 100, "stageDurationsMs": {"google": 40, "review": 60}, "completionStatus": "full_success"}},
        {"id": "degraded", "language": "en", "source": "world", "references": ["世界"], "tags": [], "replayOutput": {"translation": "世界", "durationMs": 200, "review": {"status": "unavailable"}}},
    ]
    summary = run_evaluation(
        cases,
        suite="translation",
        system="replay",
        trials=1,
        run_dir=tmp_path,
        metadata={"suite": "translation", "runId": "translation", "system": "replay"},
    )
    metrics = summary["metrics"]
    assert metrics["fullSuccessRate"] == 0.5
    assert metrics["degradationRate"] == 0.5
    assert metrics["usableSuccessRate"] == 1.0
    assert metrics["processingTimeMs"]["mean"] == 150
    assert metrics["stageTimeMs"]["google"]["mean"] == 40
    assert metrics["meanInitialChrf"] is not None
    assert metrics["meanReviewChrfDelta"] is not None


def _write_agent_run(path, run_id, passed, manifest_hash="same"):
    path.mkdir(parents=True)
    write_json(path / "summary.json", {
        "runId": run_id,
        "suite": "agent",
        "system": "agent",
        "datasetVersion": "v1",
        "manifestHash": manifest_hash,
        "complete": True,
        "metrics": {"trialSuccessRate": float(passed)},
    })
    write_jsonl(path / "raw.jsonl", [{
        "id": "agent-001",
        "trial": 1,
        "status": "success",
        "suite": "agent",
        "language": "zh",
        "input": {"message": "test"},
        "output": {"answer": "ok", "toolCalls": [], "toolResults": []},
        "metrics": {"passed": passed, "score": float(passed), "hardFailures": [] if passed else ["requiredFacts"]},
    }])


def test_compare_blocks_agent_regression_and_writes_blind_review(tmp_path):
    baseline, candidate, output = tmp_path / "baseline", tmp_path / "candidate", tmp_path / "comparison"
    _write_agent_run(baseline, "baseline", True)
    _write_agent_run(candidate, "candidate", False)
    comparison = compare_runs(baseline, candidate, output, review_limit=10)
    assert comparison["classification"] == "确认回归"
    assert comparison["hardGate"]["passed"] is False
    assert any(item.startswith("regression_case") for item in comparison["hardGate"]["failures"])
    assert (output / "report.md").is_file()
    assert len(load_jsonl(output / "blind_review.jsonl")) == 1


def _write_translation_run(path, run_id, completion, duration_ms):
    path.mkdir(parents=True)
    write_json(path / "summary.json", {
        "runId": run_id,
        "suite": "translation",
        "system": "replay",
        "datasetVersion": "v1",
        "manifestHash": "same",
        "complete": True,
        "metrics": {"entityRecall": 1.0},
    })
    write_jsonl(path / "raw.jsonl", [{
        "id": "translation-001",
        "trial": 1,
        "status": "success",
        "suite": "translation",
        "language": "en",
        "input": {"source": "hello", "references": ["你好"]},
        "output": {"translation": "你好", "durationMs": duration_ms},
        "metrics": {
            "chrf": 100.0,
            "entity": {"recall": 1.0},
            "empty": False,
            "completionStatus": completion,
            "successful": True,
            "degraded": completion == "degraded",
        },
    }])


def test_compare_reports_time_and_blocks_new_translation_degradation(tmp_path):
    baseline, candidate, output = tmp_path / "baseline", tmp_path / "candidate", tmp_path / "comparison"
    _write_translation_run(baseline, "baseline", "full_success", 100)
    _write_translation_run(candidate, "candidate", "degraded", 80)
    comparison = compare_runs(baseline, candidate, output, review_limit=10)
    assert comparison["processingTime"]["delta"] == -20
    assert comparison["outcomes"]["degraded"]["delta"] == 1
    assert "translation_outcome_regression:translation-001" in comparison["hardGate"]["failures"]
