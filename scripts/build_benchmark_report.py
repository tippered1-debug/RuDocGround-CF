from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from rudocground.io import load_gold
from rudocground.metrics import evaluate_report
from rudocground.models import normalize_answer_value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(records)
    decision_records = [row for row in records if row.get("decision_required")]
    return {
        "count": count,
        "answer_accuracy": _safe_div(sum(1 for row in records if row["answer_correct"]), count),
        "decision_accuracy": _safe_div(sum(1 for row in decision_records if row["decision_correct"]), len(decision_records)),
        "decision_required_count": len(decision_records),
        "evidence_precision": _safe_div(sum(row["evidence_precision"] for row in records), count),
        "evidence_recall": _safe_div(sum(row["evidence_recall"] for row in records), count),
        "evidence_f1": _safe_div(sum(row["evidence_f1"] for row in records), count),
        "missing_information_accuracy": _safe_div(sum(1 for row in records if row["missing_information_correct"]), count),
        "unsupported_evidence_rate": _safe_div(sum(row["unsupported_evidence_rate"] for row in records), count),
    }


def _group_metrics_by_case(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["key"]["case_id"])].append(record)
    return [{"case_id": case_id, **_aggregate(items)} for case_id, items in sorted(grouped.items())]


def _group_metrics_by_field(records: list[dict[str, Any]], field_name: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record[field_name])].append(record)
    return [{field_name: key, **_aggregate(items)} for key, items in sorted(grouped.items())]


def _build_wrong_answer_rows(gold_rows: dict[tuple[str, str, str], Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        key = record["key"]
        gold = gold_rows[(key["case_id"], key["variant_id"], key["question_id"])]
        if not record["answer_correct"]:
            try:
                expected = normalize_answer_value(gold.answer_type, gold.answer_normalized)
            except Exception:
                expected = gold.answer_normalized
            try:
                actual = normalize_answer_value(gold.answer_type, record.get("answer"))
            except Exception:
                actual = record.get("answer")
            rows.append(
                {
                    "kind": "answer_mismatch",
                    "case_id": key["case_id"],
                    "variant_id": key["variant_id"],
                    "question_id": key["question_id"],
                    "skill": (gold.model_extra or {}).get("skill", "unknown"),
                    "answer_type": gold.answer_type,
                    "expected": expected,
                    "actual": actual,
                }
            )
        if record.get("decision_required") and not record["decision_correct"]:
            rows.append(
                {
                    "kind": "decision_mismatch",
                    "case_id": key["case_id"],
                    "variant_id": key["variant_id"],
                    "question_id": key["question_id"],
                    "skill": (gold.model_extra or {}).get("skill", "unknown"),
                    "answer_type": gold.answer_type,
                    "expected": gold.decision,
                    "actual": record.get("decision"),
                }
            )
        if not record["missing_information_correct"]:
            rows.append(
                {
                    "kind": "missing_information_mismatch",
                    "case_id": key["case_id"],
                    "variant_id": key["variant_id"],
                    "question_id": key["question_id"],
                    "skill": (gold.model_extra or {}).get("skill", "unknown"),
                    "answer_type": gold.answer_type,
                    "expected": gold.missing_information,
                    "actual": record.get("missing_information"),
                }
            )
    return rows


def _aggregate_counterfactual_by_case(counterfactual_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in counterfactual_rows:
        grouped[str(row["case_id"])].append(row)
    result: list[dict[str, Any]] = []
    for case_id, items in sorted(grouped.items()):
        flip_items = [row for row in items if row.get("expected_change")]
        invariance_items = [row for row in items if not row.get("expected_change")]
        result.append(
            {
                "case_id": case_id,
                "flip_score": _safe_div(sum(row["score"] for row in flip_items), len(flip_items)),
                "flip_count": len(flip_items),
                "invariance_score": _safe_div(sum(row["score"] for row in invariance_items), len(invariance_items)),
                "invariance_count": len(invariance_items),
            }
        )
    return result


def build_report(gold_path: Path, prediction_paths: list[Path]) -> dict[str, Any]:
    combined_rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for prediction_path in prediction_paths:
        for row in _load_jsonl(prediction_path):
            key = (row["case_id"], row["variant_id"], row["question_id"])
            if key in seen_keys:
                raise ValueError(f"duplicate prediction key: {key}")
            seen_keys.add(key)
            combined_rows.append(row)
    if not combined_rows:
        raise ValueError("no predictions provided")

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".jsonl") as handle:
        temp_path = Path(handle.name)
        for row in combined_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    try:
        report = evaluate_report(str(gold_path), str(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)

    gold = load_gold(gold_path)
    gold_by_key = {row.key(): row for row in gold.records}
    records = report.records
    by_case = _group_metrics_by_case(records)
    by_answer_type = _group_metrics_by_field(records, "answer_type")
    by_skill: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = record["key"]
        gold_record = gold_by_key[(key["case_id"], key["variant_id"], key["question_id"])]
        skill = str((gold_record.model_extra or {}).get("skill", "unknown"))
        by_skill[skill].append(record)
    skill_rows = [{"skill": key, **_aggregate(items)} for key, items in sorted(by_skill.items())]
    errors = [{"kind": issue["kind"], "lineno": issue["lineno"], "message": issue["message"]} for issue in report.issues]
    errors.extend(_build_wrong_answer_rows(gold_by_key, records))
    counterfactual_by_case = _aggregate_counterfactual_by_case(report.counterfactual["rows"])

    return {
        "overall": report.overall,
        "by_case_id": by_case,
        "by_skill": skill_rows,
        "by_answer_type": by_answer_type,
        "errors": errors,
        "counterfactual": report.counterfactual,
        "counterfactual_by_case": counterfactual_by_case,
        "records": records,
        "issues": report.issues,
        "source_files": [str(path) for path in prediction_paths],
        "gold_path": str(gold_path),
        "prediction_count": len(combined_rows),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "benchmark_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    records_csv = output_dir / "benchmark_report.csv"
    _write_csv(
        records_csv,
        [
            {
                "case_id": row["key"]["case_id"],
                "variant_id": row["key"]["variant_id"],
                "question_id": row["key"]["question_id"],
                "answer_type": row["answer_type"],
                "decision_required": row["decision_required"],
                "answer_correct": row["answer_correct"],
                "decision_correct": row["decision_correct"],
                "missing_information_correct": row["missing_information_correct"],
                "evidence_precision": row["evidence_precision"],
                "evidence_recall": row["evidence_recall"],
                "evidence_f1": row["evidence_f1"],
                "unsupported_evidence_rate": row["unsupported_evidence_rate"],
            }
            for row in report["records"]
        ],
        [
            "case_id",
            "variant_id",
            "question_id",
            "answer_type",
            "decision_required",
            "answer_correct",
            "decision_correct",
            "missing_information_correct",
            "evidence_precision",
            "evidence_recall",
            "evidence_f1",
            "unsupported_evidence_rate",
        ],
    )

    _write_csv(output_dir / "metrics_by_case.csv", report["by_case_id"], ["case_id", "count", "answer_accuracy", "decision_accuracy", "decision_required_count", "evidence_precision", "evidence_recall", "evidence_f1", "missing_information_accuracy", "unsupported_evidence_rate"])
    _write_csv(output_dir / "metrics_by_skill.csv", report["by_skill"], ["skill", "count", "answer_accuracy", "decision_accuracy", "decision_required_count", "evidence_precision", "evidence_recall", "evidence_f1", "missing_information_accuracy", "unsupported_evidence_rate"])
    _write_csv(output_dir / "metrics_by_answer_type.csv", report["by_answer_type"], ["answer_type", "count", "answer_accuracy", "decision_accuracy", "decision_required_count", "evidence_precision", "evidence_recall", "evidence_f1", "missing_information_accuracy", "unsupported_evidence_rate"])
    _write_csv(output_dir / "counterfactual_by_case.csv", report["counterfactual_by_case"], ["case_id", "flip_score", "flip_count", "invariance_score", "invariance_count"])
    _write_csv(output_dir / "errors.csv", report["errors"], sorted({key for row in report["errors"] for key in row.keys()}))


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build RuDocGround-CF benchmark report tables")
    parser.add_argument("--gold", required=True)
    parser.add_argument("--predictions", nargs="+", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    report = build_report(Path(args.gold), [Path(path) for path in args.predictions])
    write_outputs(report, Path(args.output_dir))
    print(json.dumps({"output_dir": args.output_dir, "prediction_count": report["prediction_count"], "overall": report["overall"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
