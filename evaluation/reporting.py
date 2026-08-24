"""基线与候选运行的成对比较、门禁和人工盲评材料。"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

from .io import load_jsonl, write_json, write_jsonl
from .metrics import mqm_score, paired_bootstrap


def _load_run(path):
    path = Path(path)
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    latest = {}
    for row in load_jsonl(path / "raw.jsonl"):
        latest[(row.get("id"), int(row.get("trial") or 1))] = row
    return summary, latest


def _paired_rows(baseline, candidate):
    return [(baseline[key], candidate[key]) for key in sorted(set(baseline).intersection(candidate)) if baseline[key].get("status") == candidate[key].get("status") == "success"]


def _primary_value(row, suite):
    if suite == "asr":
        return float(row["metrics"]["rate"])
    if suite == "translation":
        return float(row["metrics"]["chrf"])
    return float(bool(row["metrics"]["passed"]))


def _processing_time(row):
    value = (row.get("output") or {}).get("durationMs")
    return float(value if value is not None else row.get("wallDurationMs") or 0)


def _metric_comparison(paired, path):
    before = _mean_metric(paired, path, "baseline")
    after = _mean_metric(paired, path, "candidate")
    return {
        "baseline": before,
        "candidate": after,
        "delta": after - before if before is not None and after is not None else None,
    }


def _classification(suite, paired, comparison, blocked):
    if blocked:
        return "确认回归"
    if not paired:
        return "无明确差异"
    delta = comparison["primary"]["delta"]
    low, high = comparison["primary"]["ci95"]
    if delta is None:
        return "无明确差异"
    if suite == "asr":
        languages_ok = all(item["delta"] <= 0.02 for item in comparison.get("languages", {}).values())
        entity_ok = comparison.get("entityRecallDelta", 0) >= -0.02
        timing_ok = comparison.get("timingP95DeltaSeconds") is None or comparison["timingP95DeltaSeconds"] <= 0.25
        if high < 0 and languages_ok and entity_ok and timing_ok:
            return "确认提升"
        if low > 0:
            return "确认回归"
        return "倾向提升" if delta < 0 else "无明确差异"
    if suite == "translation":
        human = comparison.get("humanReview") or {}
        if human.get("completed") and human.get("candidateWins", 0) > human.get("baselineWins", 0) and not human.get("candidateCriticalAdded"):
            return "确认提升"
        if high < 0:
            return "确认回归"
        return "倾向提升" if delta > 0 else "无明确差异"
    if low > 0:
        return "确认提升"
    if high < 0:
        return "确认回归"
    return "倾向提升" if delta > 0 else "无明确差异"


def _language_comparison(paired):
    result = {}
    languages = sorted({before["language"] for before, _after in paired})
    for language in languages:
        selected = [(before, after) for before, after in paired if before["language"] == language]
        baseline = [_primary_value(before, "asr") for before, _after in selected]
        candidate = [_primary_value(after, "asr") for _before, after in selected]
        result[language] = {"count": len(selected), "baseline": statistics.fmean(baseline), "candidate": statistics.fmean(candidate), "delta": statistics.fmean(candidate) - statistics.fmean(baseline)}
    return result


def _mean_metric(paired, path, side):
    values = []
    for before, after in paired:
        value = before if side == "baseline" else after
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if value is not None:
            values.append(float(value))
    return statistics.fmean(values) if values else None


def _hard_gates(suite, baseline_summary, candidate_summary, paired):
    failures = []
    if not baseline_summary.get("complete") or not candidate_summary.get("complete"):
        failures.append("incomplete_run")
    if suite == "agent":
        for before, after in paired:
            if before["metrics"]["passed"] and not after["metrics"]["passed"]:
                failures.append(f"regression_case:{after['id']}:trial-{after['trial']}")
            hard_checks = {
                "outputSchema", "allowed", "category", "intent", "requiredTools", "forbiddenTools",
                "toolPrecision", "toolArgs", "noSensitiveOutput", "proposal", "stateMatches", "taskCompleted",
            }
            failures.extend(
                f"agent:{after['id']}:{name}"
                for name in after["metrics"].get("hardFailures") or []
                if name in hard_checks
            )
        baseline_rate = baseline_summary.get("metrics", {}).get("trialSuccessRate")
        candidate_rate = candidate_summary.get("metrics", {}).get("trialSuccessRate")
        if baseline_rate is not None and candidate_rate is not None and candidate_rate <= baseline_rate - 0.10:
            failures.append("agent_success_rate_drop_10pp")
        for name in ("intentAccuracy", "toolRecall", "processSuccessRate", "taskCompletionRate"):
            before = baseline_summary.get("metrics", {}).get(name)
            after = candidate_summary.get("metrics", {}).get(name)
            if before is not None and after is not None and after <= before - 0.10:
                failures.append(f"agent_{name}_drop_10pp")
    elif suite == "asr":
        before_rate = baseline_summary.get("metrics", {}).get("macroErrorRate")
        after_rate = candidate_summary.get("metrics", {}).get("macroErrorRate")
        if before_rate is not None and after_rate is not None and after_rate >= before_rate + 0.05:
            failures.append("asr_macro_error_increase_5pp")
        for before, after in paired:
            before_health, after_health = before["metrics"]["segmentHealth"], after["metrics"]["segmentHealth"]
            if sum(after_health.values()) > sum(before_health.values()):
                failures.append(f"asr_timing_schema:{after['id']}")
    else:
        before_entity = baseline_summary.get("metrics", {}).get("entityRecall")
        after_entity = candidate_summary.get("metrics", {}).get("entityRecall")
        if before_entity is not None and after_entity is not None and after_entity <= before_entity - 0.05:
            failures.append("translation_entity_recall_drop_5pp")
        for before, after in paired:
            if not before["metrics"]["empty"] and after["metrics"]["empty"]:
                failures.append(f"translation_empty:{after['id']}")
            rank = {"failed": 0, "degraded": 1, "full_success": 2}
            before_status = before["metrics"].get("completionStatus", "full_success")
            after_status = after["metrics"].get("completionStatus", "full_success")
            if rank.get(after_status, 0) < rank.get(before_status, 0):
                failures.append(f"translation_outcome_regression:{after['id']}")
    return sorted(set(failures))


def _review_change(before, after, suite):
    return abs(_primary_value(after, suite) - _primary_value(before, suite))


def _review_rows(paired, suite, baseline_id, candidate_id, limit):
    ranked = sorted(paired, key=lambda pair: (-_review_change(*pair, suite), pair[0]["language"], pair[0]["id"], pair[0]["trial"]))
    selected = ranked[: min(len(ranked), max(1, limit // 2))]
    selected_keys = {(before["id"], before["trial"]) for before, _after in selected}
    remaining = [pair for pair in paired if (pair[0]["id"], pair[0]["trial"]) not in selected_keys]
    remaining.sort(key=lambda pair: (
        pair[0]["language"],
        hashlib.sha256(f"{baseline_id}:{candidate_id}:{pair[0]['id']}:{pair[0]['trial']}".encode()).hexdigest(),
    ))
    by_language = defaultdict(list)
    for pair in remaining:
        by_language[pair[0]["language"]].append(pair)
    while len(selected) < min(limit, len(paired)) and any(by_language.values()):
        for language in sorted(by_language):
            if by_language[language] and len(selected) < limit:
                selected.append(by_language[language].pop(0))
    rows, key = [], {}
    for index, (before, after) in enumerate(selected, start=1):
        review_id = f"review-{index:03d}"
        digest = hashlib.sha256(f"{baseline_id}:{candidate_id}:{before['id']}:{before['trial']}".encode()).digest()
        baseline_side = "A" if digest[0] % 2 == 0 else "B"
        sides = {baseline_side: before, "B" if baseline_side == "A" else "A": after}
        rows.append({
            "reviewId": review_id,
            "caseId": before["id"],
            "trial": before["trial"],
            "suite": suite,
            "language": before["language"],
            "input": before.get("input") or {},
            "outputA": sides["A"].get("output") or {},
            "outputB": sides["B"].get("output") or {},
            "preference": "",
            "mqmA": [],
            "mqmB": [],
            "notes": "",
        })
        key[review_id] = {"baselineSide": baseline_side, "caseId": before["id"], "trial": before["trial"]}
    return rows, key


def _human_review(annotations, key):
    if not annotations:
        return {"completed": False, "reviewed": 0}
    wins = {"baseline": 0, "candidate": 0, "tie": 0}
    baseline_mqm = candidate_mqm = 0.0
    candidate_critical_added = False
    reviewed = 0
    for row in annotations:
        mapping = key.get(row.get("reviewId"))
        preference = str(row.get("preference") or "").upper()
        if not mapping or preference not in {"A", "B", "TIE"}:
            continue
        reviewed += 1
        baseline_side = mapping["baselineSide"]
        if preference == "TIE":
            wins["tie"] += 1
        elif preference == baseline_side:
            wins["baseline"] += 1
        else:
            wins["candidate"] += 1
        input_data = row.get("input") or {}
        source_chars = len(str(input_data.get("source") or input_data.get("reference") or ""))
        baseline_errors = row.get(f"mqm{baseline_side}") or []
        candidate_side = "B" if baseline_side == "A" else "A"
        candidate_errors = row.get(f"mqm{candidate_side}") or []
        baseline_mqm += mqm_score(baseline_errors, source_chars)
        candidate_mqm += mqm_score(candidate_errors, source_chars)
        baseline_critical = sum(str(item.get("severity") or "").lower() == "critical" for item in baseline_errors)
        candidate_critical = sum(str(item.get("severity") or "").lower() == "critical" for item in candidate_errors)
        candidate_critical_added |= candidate_critical > baseline_critical
    return {
        "completed": reviewed > 0,
        "reviewed": reviewed,
        "baselineWins": wins["baseline"],
        "candidateWins": wins["candidate"],
        "ties": wins["tie"],
        "baselineMqmPer100Chars": baseline_mqm / reviewed if reviewed else None,
        "candidateMqmPer100Chars": candidate_mqm / reviewed if reviewed else None,
        "candidateCriticalAdded": candidate_critical_added,
    }


def compare_runs(baseline_dir, candidate_dir, output_dir, *, annotations_path=None, review_limit=60):
    baseline_summary, baseline_rows = _load_run(baseline_dir)
    candidate_summary, candidate_rows = _load_run(candidate_dir)
    suite = baseline_summary.get("suite")
    if suite != candidate_summary.get("suite"):
        raise ValueError("baseline 与 candidate suite 不一致")
    if baseline_summary.get("manifestHash") != candidate_summary.get("manifestHash"):
        raise ValueError("baseline 与 candidate 必须使用完全相同的 manifest")
    paired = _paired_rows(baseline_rows, candidate_rows)
    before_values = [_primary_value(before, suite) for before, _after in paired]
    after_values = [_primary_value(after, suite) for _before, after in paired]
    primary = paired_bootstrap(before_values, after_values)
    before_times = [_processing_time(before) for before, _after in paired]
    after_times = [_processing_time(after) for _before, after in paired]
    processing_time = paired_bootstrap(before_times, after_times)
    processing_time.update({
        "baselineMeanMs": statistics.fmean(before_times) if before_times else None,
        "candidateMeanMs": statistics.fmean(after_times) if after_times else None,
        "lowerIsBetter": True,
    })
    blind_rows, blind_key = _review_rows(paired, suite, baseline_summary["runId"], candidate_summary["runId"], review_limit)
    annotations = load_jsonl(annotations_path) if annotations_path else []
    human = _human_review(annotations, blind_key)
    gates = _hard_gates(suite, baseline_summary, candidate_summary, paired)
    if suite == "translation" and human.get("candidateCriticalAdded"):
        gates.append("translation_new_critical_mqm_error")
    comparison = {
        "suite": suite,
        "baselineRunId": baseline_summary["runId"],
        "candidateRunId": candidate_summary["runId"],
        "datasetVersion": baseline_summary.get("datasetVersion"),
        "pairedCases": len(paired),
        "primaryMetric": "errorRate" if suite == "asr" else "chrf" if suite == "translation" else "taskSuccess",
        "primary": primary,
        "processingTime": processing_time,
        "hardGate": {"passed": not gates, "failures": gates},
        "humanReview": human,
    }
    if suite == "asr":
        comparison["languages"] = _language_comparison(paired)
        before_entity = _mean_metric(paired, ("metrics", "entity", "recall"), "baseline")
        after_entity = _mean_metric(paired, ("metrics", "entity", "recall"), "candidate")
        comparison["entityRecallDelta"] = (after_entity - before_entity) if before_entity is not None and after_entity is not None else None
        before_timing = _mean_metric(paired, ("metrics", "timing", "p95Seconds"), "baseline")
        after_timing = _mean_metric(paired, ("metrics", "timing", "p95Seconds"), "candidate")
        comparison["timingP95DeltaSeconds"] = (after_timing - before_timing) if before_timing is not None and after_timing is not None else None
    elif suite == "translation":
        before_entity = _mean_metric(paired, ("metrics", "entity", "recall"), "baseline")
        after_entity = _mean_metric(paired, ("metrics", "entity", "recall"), "candidate")
        comparison["entityRecallDelta"] = (after_entity - before_entity) if before_entity is not None and after_entity is not None else None
        comparison["outcomes"] = {
            name: _metric_comparison(paired, ("metrics", name))
            for name in ("successful", "degraded")
        }
    else:
        comparison["agentMetrics"] = {
            name: _metric_comparison(paired, ("metrics", name))
            for name in (
                "intentCorrect", "toolPrecision", "toolRecall", "skillPrecision", "skillRecall",
                "processCorrect", "taskCompleted", "stateChanged",
            )
        }
    comparison["classification"] = _classification(suite, paired, comparison, bool(gates))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "comparison.json", comparison)
    write_jsonl(output_dir / "blind_review.jsonl", blind_rows)
    write_json(output_dir / "blind_key.json", blind_key)
    (output_dir / "report.md").write_text(render_report(comparison, baseline_summary, candidate_summary), encoding="utf-8")
    return comparison


def _percent(value):
    return "-" if value is None else f"{float(value) * 100:.2f}%"


def render_report(comparison, baseline, candidate):
    primary = comparison["primary"]
    low, high = primary["ci95"]
    lines = [
        f"# {comparison['suite']} 评测对比",
        "",
        f"- 结论：**{comparison['classification']}**",
        f"- 基线：`{comparison['baselineRunId']}`（{baseline.get('system')}）",
        f"- 候选：`{comparison['candidateRunId']}`（{candidate.get('system')}）",
        f"- 成对样本：{comparison['pairedCases']}",
        f"- 主指标差值：{primary['delta'] if primary['delta'] is not None else '-'}，95% CI = [{low}, {high}]",
        f"- 平均处理时间：{comparison['processingTime']['baselineMeanMs']} ms → {comparison['processingTime']['candidateMeanMs']} ms",
        f"- 处理时间差值：{comparison['processingTime']['delta']} ms，95% CI = {comparison['processingTime']['ci95']}",
        f"- 硬门禁：{'通过' if comparison['hardGate']['passed'] else '失败'}",
    ]
    if comparison["hardGate"]["failures"]:
        lines.extend(["", "## 门禁失败", "", *[f"- `{item}`" for item in comparison["hardGate"]["failures"]]])
    if comparison["suite"] == "asr":
        lines.extend(["", "## 语言切片", "", "| 语言 | 基线 | 候选 | 差值 |", "| --- | ---: | ---: | ---: |"])
        for language, item in comparison.get("languages", {}).items():
            lines.append(f"| {language} | {_percent(item['baseline'])} | {_percent(item['candidate'])} | {_percent(item['delta'])} |")
    elif comparison["suite"] == "translation":
        lines.extend(["", "## 成功与降级", "", "| 指标 | 基线 | 候选 | 差值 |", "| --- | ---: | ---: | ---: |"])
        for name, item in comparison.get("outcomes", {}).items():
            lines.append(f"| {name} | {_percent(item['baseline'])} | {_percent(item['candidate'])} | {_percent(item['delta'])} |")
    else:
        lines.extend(["", "## Agent 分项", "", "| 指标 | 基线 | 候选 | 差值 |", "| --- | ---: | ---: | ---: |"])
        for name, item in comparison.get("agentMetrics", {}).items():
            lines.append(f"| {name} | {_percent(item['baseline'])} | {_percent(item['candidate'])} | {_percent(item['delta'])} |")
    human = comparison.get("humanReview") or {}
    lines.extend([
        "",
        "## 人工盲评",
        "",
        f"- 已完成：{human.get('reviewed', 0)}",
        f"- 候选胜 / 平 / 基线胜：{human.get('candidateWins', 0)} / {human.get('ties', 0)} / {human.get('baselineWins', 0)}",
        f"- MQM 基线 / 候选：{human.get('baselineMqmPer100Chars', '-')} / {human.get('candidateMqmPer100Chars', '-')}",
        "- 在 `blind_review.jsonl` 填写 preference、mqmA、mqmB 后，使用 `compare --annotations` 重新生成结论。",
    ])
    return "\n".join(lines) + "\n"
