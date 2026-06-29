from __future__ import annotations

import argparse
import json
import sys

from .case_tools import audit_case, audit_source_fidelity, prepare_prompts
from .final_audit import build_full_audit, write_full_audit
from .providers.codex_cli_provider import codex_diagnostics
from .providers.ollama_provider import OllamaProvider
from .metrics import evaluate_report
from .runner import evaluate_run, run_model
from .variant_batched_compact_runner import run_variant_batched_compact
from .variant_batched_runner import run_variant_batched


def _format_pct(value: float) -> str:
    return f"{value * 100:6.2f}%"


def _print_table(report: dict) -> None:
    overall = report["overall"]
    counterfactual = report["counterfactual"]
    counterfactual_lines = []
    if "ab_flip_score" in counterfactual:
        counterfactual_lines = [
            f"A->B flip score              {_format_pct(counterfactual['ab_flip_score'])}",
            f"A->B invariance score        {_format_pct(counterfactual['ab_invariance_score'])}",
            f"A->C nuisance detection      {_format_pct(counterfactual['ac_nuisance_detection_score'])}",
            f"A->C causal invariance       {_format_pct(counterfactual['ac_causal_invariance_score'])}",
            f"Missed-update rate           {_format_pct(counterfactual['missed_update_rate'])}",
            f"Over-update rate             {_format_pct(counterfactual['over_update_rate'])}",
        ]
    else:
        counterfactual_lines = [
            f"Flip score                    {_format_pct(counterfactual['flip_score'])}",
            f"Invariance score              {_format_pct(counterfactual['invariance_score'])}",
        ]
    lines = [
        "Metric                         Value",
        "--------------------------------------",
        f"Answer accuracy               {_format_pct(overall['answer_accuracy'])}",
        f"Decision accuracy             {_format_pct(overall['decision_accuracy'])}",
        f"Decision denominator          {overall.get('decision_required_count', 0):6d}",
        f"Evidence F1                   {_format_pct(overall['evidence_f1'])}",
        f"Missing-info accuracy         {_format_pct(overall['missing_information_accuracy'])}",
        f"Unsupported evidence rate     {_format_pct(overall['unsupported_evidence_rate'])}",
    ]
    lines.extend(counterfactual_lines)
    print("\n".join(lines), file=sys.stderr)


def _print_run_summary(summary: dict) -> None:
    print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rudocground")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = subparsers.add_parser("evaluate", help="Evaluate predictions against gold JSONL")
    evaluate_parser.add_argument("--gold", required=True)
    evaluate_parser.add_argument("--predictions", required=True)
    run_parser = subparsers.add_parser("run-model", help="Run a provider against prepared prompt tasks")
    run_parser.add_argument("--prompts", required=True)
    run_parser.add_argument("--provider", required=True, choices=["openai", "gemini", "codex", "ollama", "mock"])
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--policy", default="evidence_required", choices=["answer_only", "structured", "evidence_required"])
    run_parser.add_argument("--limit", type=int)
    run_parser.add_argument("--question-id")
    run_parser.add_argument("--variant-id")
    run_parser.add_argument("--max-retries", type=int, default=3)
    run_parser.add_argument("--request-delay", type=float, default=0.0)
    run_parser.add_argument("--min-request-interval", type=float, default=0.0)
    run_parser.add_argument("--codex-binary")
    run_parser.add_argument("--resume", action="store_true")
    run_parser.add_argument("--dry-run", action="store_true")
    eval_run_parser = subparsers.add_parser("evaluate-run", help="Evaluate a saved model run and write a detailed report")
    eval_run_parser.add_argument("--gold", required=True)
    eval_run_parser.add_argument("--predictions", required=True)
    eval_run_parser.add_argument("--report", required=True)
    strict_audit_parser = subparsers.add_parser(
        "strict-audit",
        help="Write the strict end-to-end audit for a saved full release run",
    )
    strict_audit_parser.add_argument("--gold", required=True)
    strict_audit_parser.add_argument("--predictions", required=True)
    strict_audit_parser.add_argument("--prompts", required=True)
    strict_audit_parser.add_argument("--output-dir", required=True)
    strict_audit_parser.add_argument("--prefix", default="v1_3_full")
    audit_parser = subparsers.add_parser("audit-cases", help="Audit a document case package")
    audit_parser.add_argument("--case", required=True)
    source_audit_parser = subparsers.add_parser(
        "audit-source-fidelity",
        help="Audit that a case package matches its source documents",
    )
    source_audit_parser.add_argument("--case", required=True)
    source_audit_parser.add_argument("--sources", required=True)
    prompts_parser = subparsers.add_parser("prepare-prompts", help="Generate prompt files for a case package")
    prompts_parser.add_argument("--case", required=True)
    prompts_parser.add_argument("--gold", required=True)
    prompts_parser.add_argument("--output", required=True)
    check_provider_parser = subparsers.add_parser("check-provider", help="Diagnose a model provider")
    check_provider_parser.add_argument("--provider", required=True, choices=["codex", "ollama"])
    check_provider_parser.add_argument("--codex-binary")
    check_provider_parser.add_argument("--model")
    check_provider_parser.add_argument("--base-url")
    check_provider_parser.add_argument("--num-ctx", type=int)
    check_provider_parser.add_argument("--num-predict", type=int)
    check_provider_parser.add_argument("--temperature", type=float)
    check_provider_parser.add_argument("--seed", type=int)
    check_provider_parser.add_argument("--keep-alive")
    check_provider_parser.add_argument("--think", action="store_true")
    check_provider_parser.add_argument("--no-think", action="store_true")
    run_batch_parser = subparsers.add_parser("run-variant-batched", help="Run a variant-batched structured-output model sweep")
    run_batch_parser.add_argument("--prompts", required=True)
    run_batch_parser.add_argument("--gold", required=True)
    run_batch_parser.add_argument("--output", required=True)
    run_batch_parser.add_argument("--report", required=True)
    run_batch_parser.add_argument("--counterfactual", required=True)
    run_batch_parser.add_argument("--manifest", required=True)
    run_batch_parser.add_argument("--model", default="qwen3:8b")
    run_batch_parser.add_argument("--base-url", default="http://127.0.0.1:11434/api/chat")
    run_batch_parser.add_argument("--num-ctx", type=int, default=16384)
    run_batch_parser.add_argument("--num-predict", type=int, default=4096)
    run_batch_parser.add_argument("--temperature", type=float, default=0.0)
    run_batch_parser.add_argument("--seed", type=int, default=42)
    run_batch_parser.add_argument("--keep-alive", default="30m")
    run_batch_parser.add_argument("--resume", action="store_true")
    run_batch_parser.add_argument("--dry-run", action="store_true")
    run_compact_parser = subparsers.add_parser("run-variant-batched-compact", help="Run a compact variant-batched structured-output model sweep")
    run_compact_parser.add_argument("--prompts", required=True)
    run_compact_parser.add_argument("--gold", required=True)
    run_compact_parser.add_argument("--output", required=True)
    run_compact_parser.add_argument("--report", required=True)
    run_compact_parser.add_argument("--counterfactual", required=True)
    run_compact_parser.add_argument("--manifest", required=True)
    run_compact_parser.add_argument("--model", default="qwen3:8b")
    run_compact_parser.add_argument("--base-url", default="http://127.0.0.1:11434/api/chat")
    run_compact_parser.add_argument("--temperature", type=float, default=0.0)
    run_compact_parser.add_argument("--seed", type=int, default=42)
    run_compact_parser.add_argument("--keep-alive", default="30m")
    run_compact_parser.add_argument("--resume", action="store_true")
    run_compact_parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        result = evaluate_report(args.gold, args.predictions)
        report = {
            "overall": result.overall,
            "by_answer_type": result.by_answer_type,
            "counterfactual": result.counterfactual,
            "records": result.records,
            "issues": result.issues,
        }
        _print_table(report)
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    if args.command == "run-model":
        summary = run_model(
            args.prompts,
            args.provider,
            args.model,
            args.output,
            policy=args.policy,
            limit=args.limit,
            question_id=args.question_id,
            variant_id=args.variant_id,
            max_retries=args.max_retries,
            request_delay=args.request_delay,
            min_request_interval=args.min_request_interval,
            codex_binary=args.codex_binary,
            resume=args.resume,
            dry_run=args.dry_run,
        )
        _print_run_summary(
            {
                "output_path": str(summary.output_path),
                "total_tasks": summary.total_tasks,
                "selected_tasks": summary.selected_tasks,
                "successful": summary.successful,
                "failed": summary.failed,
                "skipped": summary.skipped,
                "run_id": summary.run_id,
                "dry_run": args.dry_run,
            }
        )
        return 0
    if args.command == "evaluate-run":
        report = evaluate_run(args.gold, args.predictions, args.report)
        print(json.dumps(report["overall"], ensure_ascii=False, indent=2), file=sys.stderr)
        print(json.dumps(report["variant_metrics"], ensure_ascii=False, indent=2), file=sys.stderr)
        print(json.dumps(report["q6_q7"], ensure_ascii=False, indent=2), file=sys.stderr)
        print(json.dumps(report["wrong_answers"], ensure_ascii=False, indent=2), file=sys.stderr)
        print(json.dumps(report["errors_by_skill"], ensure_ascii=False, indent=2), file=sys.stderr)
        print(args.report, file=sys.stderr)
        return 0
    if args.command == "strict-audit":
        audit = build_full_audit(gold_path=args.gold, predictions_path=args.predictions, prompts_path=args.prompts)
        manifest = write_full_audit(audit, args.output_dir, prefix=args.prefix)
        strict = audit["layers"]["strict_end_to_end"]
        summary = {
            "strict_end_to_end": strict,
            "key_alignment": audit["key_alignment"],
            "counts": audit["counts"],
            "artifacts": manifest,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)
        return 0
    if args.command == "audit-cases":
        audit_case(args.case)
        print("audit-cases: ok", file=sys.stderr)
        return 0
    if args.command == "audit-source-fidelity":
        summary = audit_source_fidelity(args.case, args.sources)
        print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
        return 0
    if args.command == "prepare-prompts":
        counts = prepare_prompts(args.case, args.gold, args.output)
        print(json.dumps(counts, ensure_ascii=False), file=sys.stderr)
        return 0
    if args.command == "check-provider":
        if args.provider == "codex":
            report = codex_diagnostics(args.codex_binary)
            print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
            return 0
        if args.provider == "ollama":
            provider = OllamaProvider(
                model=args.model or "qwen3:8b",
                base_url=args.base_url or "http://127.0.0.1:11434/api/chat",
                num_ctx=args.num_ctx or 16384,
                num_predict=args.num_predict if args.num_predict is not None else 1024,
                temperature=args.temperature if args.temperature is not None else 0.0,
                seed=args.seed if args.seed is not None else 42,
                keep_alive=args.keep_alive or "30m",
                think=bool(args.think and not args.no_think),
            )
            report = provider.diagnostics()
            print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
            return 0
    if args.command == "run-variant-batched":
        report = run_variant_batched(
            prompts_path=args.prompts,
            gold_path=args.gold,
            output_path=args.output,
            report_path=args.report,
            counterfactual_path=args.counterfactual,
            manifest_path=args.manifest,
            model=args.model,
            base_url=args.base_url,
            num_ctx=args.num_ctx,
            num_predict=args.num_predict,
            temperature=args.temperature,
            seed=args.seed,
            keep_alive=args.keep_alive,
            resume=args.resume,
            dry_run=args.dry_run,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        return 0
    if args.command == "run-variant-batched-compact":
        report = run_variant_batched_compact(
            prompts_path=args.prompts,
            gold_path=args.gold,
            output_path=args.output,
            report_path=args.report,
            counterfactual_path=args.counterfactual,
            manifest_path=args.manifest,
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
            seed=args.seed,
            keep_alive=args.keep_alive,
            resume=args.resume,
            dry_run=args.dry_run,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
