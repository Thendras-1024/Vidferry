"""Vidferry 评测命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .io import (
    DEFAULT_MANIFEST_ROOT,
    DEFAULT_RESULT_ROOT,
    load_jsonl,
    run_metadata,
    safe_run_directory,
    validate_manifest,
    write_json,
)
from .manifests import initialize_manifests
from .reporting import compare_runs
from .suites import run_evaluation


DEFAULT_SYSTEMS = {"asr": "faster-whisper", "translation": "google-review", "agent": "agent"}
SYSTEMS = {
    "asr": ("faster-whisper", "replay"),
    "translation": ("google", "review", "google-review", "replay"),
    "agent": ("agent", "replay"),
}


def build_parser():
    parser = argparse.ArgumentParser(description="Vidferry 可重复效果评测")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="运行一个评测 suite")
    run.add_argument("--suite", choices=tuple(DEFAULT_SYSTEMS), required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--manifest", type=Path)
    run.add_argument("--system")
    run.add_argument("--trials", type=int, default=3)
    run.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    run.add_argument("--resume", action="store_true")

    compare = commands.add_parser("compare", help="比较基线和候选运行")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    compare.add_argument("--output-id")
    compare.add_argument("--annotations", type=Path)
    compare.add_argument("--review-limit", type=int, default=60)
    compare.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)

    validate = commands.add_parser("validate", help="只校验清单")
    validate.add_argument("--suite", choices=tuple(DEFAULT_SYSTEMS), required=True)
    validate.add_argument("--manifest", type=Path)
    validate.add_argument("--system")

    initialize = commands.add_parser("init", help="生成 v1 标注工作清单")
    initialize.add_argument("--root", type=Path, default=DEFAULT_MANIFEST_ROOT)
    initialize.add_argument("--force", action="store_true")
    return parser


def _manifest(args):
    return args.manifest or DEFAULT_MANIFEST_ROOT / f"{args.suite}.jsonl"


def _system(args):
    system = args.system or DEFAULT_SYSTEMS[args.suite]
    if system not in SYSTEMS[args.suite]:
        raise ValueError(f"suite {args.suite} 不支持 system {system}，可选值为 {', '.join(SYSTEMS[args.suite])}")
    return system


def _validate(args):
    manifest, system = _manifest(args), _system(args)
    cases = load_jsonl(manifest)
    errors = validate_manifest(cases, args.suite, system=system)
    if errors:
        _print_manifest_errors(args.suite, errors)
        return 2
    print(f"eval manifest valid : suite = {args.suite} | cases = {len(cases)} | file = {manifest}")
    return 0


def _run(args, argv):
    manifest, system = _manifest(args), _system(args)
    cases = load_jsonl(manifest)
    errors = validate_manifest(cases, args.suite, system=system)
    if errors:
        _print_manifest_errors(args.suite, errors)
        return 2
    run_dir = safe_run_directory(args.run_id, args.result_root, resume=args.resume)
    metadata = run_metadata(run_id=args.run_id, suite=args.suite, system=system, manifest=manifest, command=argv)
    metadata["trials"] = max(1, args.trials) if args.suite == "agent" else 1
    existing_metadata_path = run_dir / "metadata.json"
    if args.resume and existing_metadata_path.is_file():
        existing = json.loads(existing_metadata_path.read_text(encoding="utf-8"))
        fields = ("suite", "system", "manifestHash")
        mismatched = [field for field in fields if existing.get(field) != metadata.get(field)]
        if mismatched:
            raise ValueError(f"--resume 运行契约不一致 : fields = {','.join(mismatched)}")
        metadata["resumedAt"] = metadata["createdAt"]
        metadata["createdAt"] = existing.get("createdAt") or metadata["createdAt"]
    write_json(run_dir / "metadata.json", metadata)
    summary = run_evaluation(
        cases,
        suite=args.suite,
        system=system,
        trials=max(1, args.trials),
        run_dir=run_dir,
        metadata=metadata,
        resume=args.resume,
    )
    (run_dir / "report.md").write_text(_run_report(summary), encoding="utf-8")
    print(f"eval run finished : suite = {args.suite} | run_id = {args.run_id} | succeeded = {summary['succeeded']} | failed = {summary['failed']}")
    return 0 if summary["complete"] else 2


def _resolve_run(value, root):
    path = Path(value)
    return path if path.is_dir() else Path(root) / value


def _compare(args):
    baseline = _resolve_run(args.baseline, args.result_root)
    candidate = _resolve_run(args.candidate, args.result_root)
    output_id = args.output_id or f"compare-{baseline.name}--{candidate.name}"
    output_dir = safe_run_directory(output_id, args.result_root)
    try:
        comparison = compare_runs(
            baseline,
            candidate,
            output_dir,
            annotations_path=args.annotations,
            review_limit=max(1, args.review_limit),
        )
    except Exception:
        if output_dir.is_dir() and not any(output_dir.iterdir()):
            output_dir.rmdir()
        raise
    classification_code = {
        "确认提升": "confirmed_improvement",
        "倾向提升": "likely_improvement",
        "无明确差异": "no_clear_difference",
        "确认回归": "confirmed_regression",
    }.get(comparison["classification"], "unknown")
    print(f"eval compare finished : baseline = {baseline.name} | candidate = {candidate.name} | classification = {classification_code} | hard_gate = {comparison['hardGate']['passed']}")
    return 0 if comparison["hardGate"]["passed"] else 3


def _run_report(summary):
    return "\n".join([
        f"# {summary['suite']} 评测运行",
        "",
        f"- Run ID：`{summary['runId']}`",
        f"- System：`{summary['system']}`",
        f"- 数据集：`{summary['datasetVersion']}`",
        f"- 完成：{'是' if summary['complete'] else '否'}",
        f"- 成功 / 失败：{summary['succeeded']} / {summary['failed']}",
        "",
        "## 指标",
        "",
        "```json",
        json.dumps(summary.get("metrics") or {}, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ])


def _print_manifest_errors(suite, errors, limit=20):
    for error in errors[:limit]:
        print(f"eval manifest invalid : suite = {suite} | {error}", file=sys.stderr)
    if len(errors) > limit:
        print(f"eval manifest invalid : suite = {suite} | omitted_errors = {len(errors) - limit}", file=sys.stderr)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            paths = initialize_manifests(args.root, force=args.force)
            print(f"eval manifests initialized : root = {args.root} | files = {len(paths)}")
            return 0
        if args.command == "validate":
            return _validate(args)
        if args.command == "run":
            return _run(args, argv)
        return _compare(args)
    except Exception as exc:
        print(f"eval command failed : command = {args.command} | error_type = {exc.__class__.__name__} | reason = {' '.join(str(exc).split())[:300]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
