from __future__ import annotations

import json
from pathlib import Path

from rudocground.cli import main


def test_strict_audit_cli_writes_full_release_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "audit"
    exit_code = main(
        [
            "strict-audit",
            "--gold",
            "data/v1_3_full_gold.jsonl",
            "--predictions",
            "results/qwen3.5-4b_v1.3.1_independent_full_predictions.jsonl",
            "--prompts",
            "prompts/v1_3_full_prompts.jsonl",
            "--output-dir",
            str(output_dir),
            "--prefix",
            "v1_3_full",
        ]
    )

    assert exit_code == 0
    report = json.loads((output_dir / "v1_3_full_report_corrected.json").read_text(encoding="utf-8"))
    strict = report["layers"]["strict_end_to_end"]
    assert strict["answer_accuracy"]["denominator"] == 1160
    assert strict["answer_accuracy"]["value"] == 0.28448275862068967
    assert strict["decision_accuracy"]["value"] == 0.4834054834054834
    assert strict["evidence_f1"]["value"] == 0.42535851122058016

