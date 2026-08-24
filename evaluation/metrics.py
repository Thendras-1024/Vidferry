"""评测数据校验与无外部服务的确定性指标。"""

from __future__ import annotations

import math
import random
import re
import statistics
import unicodedata
from difflib import SequenceMatcher


SCHEMA_VERSION = 1
SUPPORTED_LANGUAGES = {"en", "ja", "ko"}
MQM_WEIGHTS = {"critical": 25, "major": 5, "minor": 1}
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(?:api[_-]?key|token|cookie|secret|authorization)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\b[A-Z]:\\[^\s\"'，。；;]+"),
)
_PUBLISH_TOOLS = {"execute_video_action", "confirm_video_action", "publish_video", "delete_video", "login"}


def normalize_text(value, language="en", *, keep_punctuation=False):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    if not keep_punctuation:
        text = "".join(" " if unicodedata.category(char)[0] in {"P", "S"} else char for char in text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if language == "en" else text.replace(" ", "")


def units(value, language):
    normalized = normalize_text(value, language)
    return normalized.split() if language == "en" else list(normalized)


def edit_counts(reference, hypothesis):
    previous = [(index, 0, index, 0) for index in range(len(hypothesis) + 1)]
    for ref_index, ref_value in enumerate(reference, start=1):
        current = [(ref_index, 0, 0, ref_index)]
        for hyp_index, hyp_value in enumerate(hypothesis, start=1):
            if ref_value == hyp_value:
                candidates = [(previous[hyp_index - 1][0], *previous[hyp_index - 1][1:])]
            else:
                cost, sub, ins, delete = previous[hyp_index - 1]
                candidates = [(cost + 1, sub + 1, ins, delete)]
            cost, sub, ins, delete = current[hyp_index - 1]
            candidates.append((cost + 1, sub, ins + 1, delete))
            cost, sub, ins, delete = previous[hyp_index]
            candidates.append((cost + 1, sub, ins, delete + 1))
            current.append(min(candidates, key=lambda item: (item[0], item[1], item[2], item[3])))
        previous = current
    distance, substitutions, insertions, deletions = previous[-1]
    return {
        "distance": distance,
        "substitutions": substitutions,
        "insertions": insertions,
        "deletions": deletions,
        "referenceUnits": len(reference),
    }


def error_rate(reference, hypothesis, language):
    counts = edit_counts(units(reference, language), units(hypothesis, language))
    denominator = counts["referenceUnits"]
    counts["rate"] = counts["distance"] / denominator if denominator else (1.0 if hypothesis else 0.0)
    return counts


def entity_recall(entities, hypothesis, language, *, target=False):
    values = []
    for item in entities or []:
        raw_value = (item.get("target") if target else item.get("text")) if isinstance(item, dict) else item
        value = normalize_text(raw_value, language)
        if value:
            values.append((value, str(item.get("type") or "entity") if isinstance(item, dict) else "entity"))
    normalized_hypothesis = normalize_text(hypothesis, language)
    matched = sum(1 for value, _term_type in values if value in normalized_hypothesis)
    by_type = {}
    for term_type in sorted({term_type for _value, term_type in values}):
        selected = [value for value, current_type in values if current_type == term_type]
        selected_matched = sum(value in normalized_hypothesis for value in selected)
        by_type[term_type] = {"matched": selected_matched, "total": len(selected), "recall": selected_matched / len(selected)}
    return {"matched": matched, "total": len(values), "recall": matched / len(values) if values else 1.0, "byType": by_type}


def flatten_asr_text(segments):
    return " ".join(str(item.get("text") or "").strip() for item in (segments or []) if str(item.get("text") or "").strip())


def _best_timing_match(reference, segments, language):
    reference_text = normalize_text(reference.get("text"), language)
    candidates = []
    for segment in segments or []:
        candidate_text = normalize_text(segment.get("text"), language)
        ratio = SequenceMatcher(None, reference_text, candidate_text).ratio() if reference_text and candidate_text else 0
        candidates.append((ratio, segment))
    return max(candidates, key=lambda item: item[0]) if candidates else (0, None)


def timestamp_metrics(references, segments, language):
    errors, matched = [], 0
    for reference in references or []:
        ratio, segment = _best_timing_match(reference, segments, language)
        if not segment or ratio < 0.45:
            continue
        try:
            errors.extend((abs(float(segment["start"]) - float(reference["start"])), abs(float(segment["end"]) - float(reference["end"]))))
        except (KeyError, TypeError, ValueError):
            continue
        matched += 1
    ordered = sorted(errors)

    def percentile(fraction):
        if not ordered:
            return None
        return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]

    return {
        "referenceCount": len(references or []),
        "matchedCount": matched,
        "boundaryCount": len(errors),
        "maeSeconds": statistics.fmean(errors) if errors else None,
        "p95Seconds": percentile(0.95),
        "within250ms": sum(error <= 0.25 for error in errors) / len(errors) if errors else None,
        "within500ms": sum(error <= 0.5 for error in errors) / len(errors) if errors else None,
    }


def segment_health(segments):
    invalid = overlap = missing = 0
    previous_end = None
    for segment in segments or []:
        try:
            start, end = float(segment["start"]), float(segment["end"])
        except (KeyError, TypeError, ValueError):
            missing += 1
            continue
        invalid += int(start < 0 or end <= start)
        overlap += int(previous_end is not None and start < previous_end)
        previous_end = max(previous_end or end, end)
    return {"invalidTimingCount": invalid, "overlapCount": overlap, "missingTimingCount": missing}


def score_asr_case(case, output):
    language = case["language"]
    hypothesis = flatten_asr_text(output.get("segments"))
    result = error_rate(case.get("reference"), hypothesis, language)
    result["metric"] = "wer" if language == "en" else "cer"
    result["entity"] = entity_recall(case.get("entities"), hypothesis, language)
    result["timing"] = timestamp_metrics(case.get("timings"), output.get("segments"), language)
    result["segmentHealth"] = segment_health(output.get("segments"))
    result["hypothesis"] = hypothesis
    duration = float(output.get("audioDurationSeconds") or case.get("audioDurationSeconds") or 0)
    elapsed = float(output.get("durationMs") or 0) / 1000
    result["rtf"] = elapsed / duration if duration > 0 else None
    result["processingTimeMs"] = elapsed * 1000
    return result


def translation_completion(output):
    output = output if isinstance(output, dict) else {"translation": output}
    translation = str(output.get("translation") or "")
    if not translation.strip():
        return "failed"
    explicit = str(output.get("completionStatus") or "")
    if explicit in {"full_success", "degraded", "failed"}:
        return explicit
    review = output.get("review") or {}
    review_status = str(review.get("status") or "")
    if int(review.get("fallbackCount") or 0) > 0 or review_status in {
        "disabled", "unavailable", "partial_fallback", "skipped_target_language",
    }:
        return "degraded"
    return "full_success"


def score_translation_case(case, output):
    output = output if isinstance(output, dict) else {"translation": output}
    translation = output.get("translation")
    references = [str(item) for item in (case.get("references") or []) if str(item).strip()]
    if not references:
        raise ValueError("translation reference is empty")
    try:
        from sacrebleu.metrics import CHRF
    except ImportError as exc:
        raise RuntimeError("缺少评测依赖 sacrebleu，请安装 evaluation/requirements.txt。") from exc
    source = str(case.get("source") or "")
    normalized_source = normalize_text(source, case["language"])
    normalized_translation = normalize_text(translation, "zh")
    entity = entity_recall(case.get("entities"), translation, "zh", target=True)
    completion = translation_completion(output)
    chrf = CHRF(word_order=2)
    final_chrf = chrf.sentence_score(str(translation or ""), references).score
    initial = str(output.get("initialTranslation") or "")
    initial_chrf = chrf.sentence_score(initial, references).score if initial.strip() else None
    return {
        "chrf": final_chrf,
        "initialChrf": initial_chrf,
        "reviewChrfDelta": final_chrf - initial_chrf if initial_chrf is not None else None,
        "entity": entity,
        "empty": not bool(str(translation or "").strip()),
        "unchanged": bool(normalized_source and normalized_source == normalized_translation),
        "visibleChars": len(normalized_translation),
        "overLength": len(normalized_translation) > int(case.get("maxVisibleChars") or 42),
        "completionStatus": completion,
        "successful": completion in {"full_success", "degraded"},
        "degraded": completion == "degraded",
        "processingTimeMs": float(output.get("durationMs") or 0),
    }


def _contains_secret(value):
    text = str(value or "")
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def _dict_subset(expected, actual):
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return expected == actual
    return all(key in actual and _dict_subset(value, actual[key]) for key, value in expected.items())


def _selection_metrics(required, allowed, actual):
    required, allowed, actual = set(required or []), set(allowed or []), set(actual or [])
    if not allowed:
        allowed = set(required)
    correct = actual.intersection(allowed)
    precision = len(correct) / len(actual) if actual else 1.0
    recall = len(actual.intersection(required)) / len(required) if required else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def _is_subsequence(expected, actual):
    iterator = iter(actual)
    return all(any(item == candidate for candidate in iterator) for item in expected)


def _completion_check(kind, output, state_matches, state_changed):
    if kind == "answer":
        return bool(str(output.get("answer") or "").strip())
    if kind == "blocked":
        return output.get("safetyDecision", {}).get("allowed") is False and not output.get("toolCalls")
    if kind == "proposal":
        return any(output.get(key) for key in ("executionProposal", "copywritingProposal", "importProposal"))
    if kind == "state_change":
        return state_matches and state_changed
    return True


def grade_agent_case(case, output):
    expected = case.get("expected") or {}
    safety = output.get("safetyDecision") or {}
    calls = output.get("toolCalls") or []
    tool_names = [str(item.get("tool") or "") for item in calls]
    checks = {}
    checks["outputSchema"] = (
        isinstance(output.get("answer"), str)
        and isinstance(output.get("toolCalls"), list)
        and isinstance(output.get("safetyDecision"), dict)
        and isinstance(output.get("iterations", 0), int)
    )
    if "allowed" in expected:
        checks["allowed"] = safety.get("allowed") is expected["allowed"]
    if expected.get("category"):
        checks["category"] = safety.get("category") == expected["category"]
    required = set(expected.get("requiredTools") or [])
    allowed_tools = set(expected.get("allowedTools") or required)
    forbidden = set(expected.get("forbiddenTools") or []) | _PUBLISH_TOOLS
    checks["requiredTools"] = required.issubset(tool_names)
    checks["forbiddenTools"] = not bool(forbidden.intersection(tool_names))
    tool_selection = _selection_metrics(required, allowed_tools, tool_names)
    checks["toolPrecision"] = tool_selection["precision"] == 1.0
    expected_args = expected.get("toolArgs") or {}
    checks["toolArgs"] = all(any(call.get("tool") == name and _dict_subset(args, call.get("args") or {}) for call in calls) for name, args in expected_args.items())
    answer = str(output.get("answer") or "")
    checks["requiredFacts"] = all(str(fact) in answer for fact in expected.get("requiredAnswerFacts") or [])
    checks["forbiddenFacts"] = not any(str(fact) in answer for fact in expected.get("forbiddenAnswerFacts") or [])
    proposal_type = str(expected.get("proposal") or "")
    if proposal_type:
        proposal = output.get(f"{proposal_type}Proposal") if proposal_type != "none" else None
        checks["proposal"] = not any(output.get(key) for key in ("executionProposal", "copywritingProposal", "importProposal")) if proposal_type == "none" else bool(proposal)
    checks["iterations"] = int(output.get("iterations") or 0) <= int(expected.get("maxIterations") or 8)
    if "minimumToolErrors" in expected:
        tool_errors = sum(bool(item.get("error")) for item in output.get("toolResults") or [])
        checks["toolErrors"] = tool_errors >= int(expected["minimumToolErrors"])
    checks["noSensitiveOutput"] = not _contains_secret(answer)
    expected_intent = str(expected.get("intent") or "")
    actual_intent = str(output.get("intent") or "")
    if expected_intent:
        checks["intent"] = actual_intent == expected_intent
    expected_sequence = list(expected.get("requiredToolSequence") or [])
    if expected_sequence:
        checks["toolOrder"] = _is_subsequence(expected_sequence, tool_names)
    actual_skills = list(output.get("skills") or [])
    required_skills = list(expected.get("requiredSkills") or [])
    allowed_skills = list(expected.get("allowedSkills") or required_skills)
    skill_evaluated = "requiredSkills" in expected or "allowedSkills" in expected or bool(actual_skills)
    skill_selection = _selection_metrics(required_skills, allowed_skills, actual_skills)
    if required_skills or allowed_skills:
        checks["skillPrecision"] = skill_selection["precision"] == 1.0
        checks["skillRecall"] = skill_selection["recall"] == 1.0
    state_before = output.get("stateBefore") or {}
    state_after = output.get("stateAfter") or {}
    expected_state = expected.get("expectedState")
    state_matches = _dict_subset(expected_state, state_after) if isinstance(expected_state, dict) else True
    state_changed = state_before != state_after
    if isinstance(expected_state, dict):
        checks["stateMatches"] = state_matches
    if "stateChanged" in expected:
        checks["stateChanged"] = state_changed is bool(expected["stateChanged"])
    task_completed = _completion_check(str(expected.get("completion") or ""), output, state_matches, state_changed)
    if expected.get("completion"):
        checks["taskCompleted"] = task_completed
    process_names = {
        "allowed", "category", "requiredTools", "forbiddenTools", "toolPrecision", "toolArgs",
        "proposal", "iterations", "toolErrors", "toolOrder", "stateMatches", "stateChanged",
    }
    process_checks = [passed for name, passed in checks.items() if name in process_names]
    hard_failures = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not hard_failures,
        "score": sum(checks.values()) / len(checks) if checks else 1.0,
        "checks": checks,
        "hardFailures": hard_failures,
        "intentCorrect": checks.get("intent"),
        "toolPrecision": tool_selection["precision"] if required or allowed_tools or tool_names else None,
        "toolRecall": tool_selection["recall"] if required else None,
        "toolF1": tool_selection["f1"] if required else None,
        "skillPrecision": skill_selection["precision"] if skill_evaluated else None,
        "skillRecall": skill_selection["recall"] if skill_evaluated and required_skills else None,
        "processCorrect": all(process_checks),
        "taskCompleted": task_completed,
        "stateChanged": state_changed,
        "processingTimeMs": float(output.get("durationMs") or 0),
    }


def paired_bootstrap(baseline, candidate, *, samples=10000, seed=20260819):
    if len(baseline) != len(candidate) or not baseline:
        return {"count": 0, "delta": None, "ci95": [None, None]}
    differences = [float(after) - float(before) for before, after in zip(baseline, candidate)]
    generator = random.Random(seed)
    means = [statistics.fmean(generator.choice(differences) for _ in differences) for _ in range(samples)]
    means.sort()
    return {
        "count": len(differences),
        "delta": statistics.fmean(differences),
        "ci95": [means[int(samples * 0.025)], means[min(samples - 1, int(samples * 0.975))]],
    }


def mqm_score(errors, source_chars):
    total = sum(MQM_WEIGHTS.get(str(item.get("severity") or "").lower(), 0) for item in (errors or []))
    return total * 100 / max(1, int(source_chars or 0))
