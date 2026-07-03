from __future__ import annotations

import argparse
import json
from pathlib import Path

from rudocground.statistics import build_statistics_artifacts


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build case-clustered bootstrap and protocol-effect statistics for RuDocGround-CF v1.3.1")
    parser.add_argument("--gold", default="data/gold.jsonl")
    parser.add_argument("--independent-predictions", default="results/qwen3.5-4b_v1.3.1_independent_full_predictions.jsonl")
    parser.add_argument("--independent-counterfactual", default="results/qwen3.5-4b_v1.3.1_independent_full_counterfactual_corrected.json")
    parser.add_argument("--independent-bundle", default="results/qwen3.5-4b_v1.3.1_release_bundle.json")
    parser.add_argument("--batched-report", default="results/qwen3.5-4b_v1.3.1_compact_full_report.json")
    parser.add_argument("--batched-counterfactual", default="results/qwen3.5-4b_v1.3.1_compact_full_counterfactual.json")
    parser.add_argument("--batched-manifest", default="results/qwen3.5-4b_v1.3.1_compact_full_manifest.json")
    parser.add_argument("--output-dir", default="results")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--replicates", type=int, default=10_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    summary = build_statistics_artifacts(
        gold_path=args.gold,
        independent_predictions_path=args.independent_predictions,
        independent_counterfactual_path=args.independent_counterfactual,
        independent_release_bundle_path=args.independent_bundle,
        batched_report_path=args.batched_report,
        batched_counterfactual_path=args.batched_counterfactual,
        batched_manifest_path=args.batched_manifest,
        output_dir=args.output_dir,
        seed=args.seed,
        replicates=args.replicates,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
