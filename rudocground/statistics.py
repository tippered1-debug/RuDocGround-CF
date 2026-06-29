from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import csv
import json
import math
import random
import subprocess
import tempfile
from statistics import median

from .io import load_gold
from .models import normalize_answer_value, normalize_evidence, normalize_evidence_doc_ids


BOOTSTRAP_CASE_COUNT = 30


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _last_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["case_id"]), str(row["variant_id"]), str(row["question_id"]))
        latest[key] = row
    return latest


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = quantile * (len(ordered) - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return ordered[low]
    frac = pos - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def _bootstrap_summary(values: list[float], *, point_estimate: float) -> dict[str, float]:
    return {
        "point_estimate": point_estimate,
        "median": median(values) if values else 0.0,
        "ci_low": _percentile(values, 0.025),
        "ci_high": _percentile(values, 0.975),
        "p_gt_0": _safe_div(sum(1 for value in values if value > 0), len(values)),
    }


def _case_ids_from_gold(gold_path: str | Path) -> list[str]:
    gold = load_gold(gold_path)
    return sorted({record.case_id for record in gold.records})


@dataclass(frozen=True)
class CaseStats:
    case_id: str
    total_rows: int
    valid_rows: int
    format_failures: int
    answer_correct: int
    decision_required: int
    decision_correct: int
    missing_correct: int
    evidence_precision_sum: float
    evidence_recall_sum: float
    evidence_f1_sum: float
    unsupported_sum: float
    counterfactual: dict[str, dict[str, float]]

    @property
    def format_success_rate(self) -> float:
        return _safe_div(self.valid_rows, self.total_rows)


@dataclass(frozen=True)
class ProtocolDataset:
    name: str
    case_stats: dict[str, CaseStats]
    point_estimates: dict[str, Any]
    total_rows: int
    case_ids: list[str]


def _row_evidence_metrics(gold_row: Any, pred_row: dict[str, Any], valid_row: bool) -> tuple[float, float, float, float]:
    if not valid_row:
        return 0.0, 0.0, 0.0, 0.0
    gold_supporting = normalize_evidence_doc_ids(gold_row.required_evidence or gold_row.supporting_evidence)
    pred_supporting = normalize_evidence_doc_ids(pred_row.get("evidence") or pred_row.get("supporting_evidence"))
    gold_set = set(gold_supporting)
    pred_set = set(pred_supporting)
    if not pred_set and not gold_set:
        return 1.0, 1.0, 1.0, 0.0
    tp = len(pred_set & gold_set)
    precision = _safe_div(tp, len(pred_set))
    recall = _safe_div(tp, len(gold_set))
    f1 = _safe_div(2 * precision * recall, precision + recall)
    unsupported = _safe_div(len(pred_set - gold_set), len(pred_set))
    return precision, recall, f1, unsupported


def _build_case_stats_from_independent(
    *,
    gold_path: str | Path,
    predictions_path: str | Path,
    counterfactual_path: str | Path,
    point_estimates: dict[str, Any],
    name: str = "independent_single_question",
) -> ProtocolDataset:
    gold = load_gold(gold_path)
    latest = _last_by_key(_load_jsonl(predictions_path))
    cf_rows = _load_json(counterfactual_path)["rows"]

    cf_by_case: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in cf_rows:
        cf_by_case[str(row["case_id"])][str(row["namespace"])].append(row)

    case_stats: dict[str, CaseStats] = {}
    grouped_gold: dict[str, list[Any]] = defaultdict(list)
    for record in gold.records:
        grouped_gold[record.case_id].append(record)

    for case_id in sorted(grouped_gold):
        gold_rows = grouped_gold[case_id]
        total_rows = len(gold_rows)
        valid_rows = 0
        answer_correct = 0
        decision_required = 0
        decision_correct = 0
        missing_correct = 0
        evidence_precision_sum = 0.0
        evidence_recall_sum = 0.0
        evidence_f1_sum = 0.0
        unsupported_sum = 0.0
        for gold_row in gold_rows:
            pred_row = latest[(gold_row.case_id, gold_row.variant_id, gold_row.question_id)]
            valid = pred_row.get("status") == "ok" and not bool(pred_row.get("evaluation_contaminated"))
            if valid:
                valid_rows += 1
            try:
                gold_answer = normalize_answer_value(gold_row.answer_type, gold_row.answer_normalized)
            except Exception:
                gold_answer = None
            pred_answer = None
            if valid:
                try:
                    pred_answer = normalize_answer_value(gold_row.answer_type, pred_row.get("answer"))
                except Exception:
                    pred_answer = None
            answer_correct += int(valid and pred_answer == gold_answer)
            if gold_row.decision_required:
                decision_required += 1
                decision_correct += int(valid and pred_row.get("decision") == gold_row.decision)
            gold_missing = set(normalize_evidence(gold_row.missing_information))
            pred_missing = set(normalize_evidence(pred_row.get("missing_information"))) if valid else set()
            missing_correct += int(valid and pred_missing == gold_missing)
            precision, recall, f1, unsupported = _row_evidence_metrics(gold_row, pred_row, valid)
            evidence_precision_sum += precision
            evidence_recall_sum += recall
            evidence_f1_sum += f1
            unsupported_sum += unsupported

        counterfactual = _summarize_case_counterfactual(case_id, cf_by_case.get(case_id, {}))
        case_stats[case_id] = CaseStats(
            case_id=case_id,
            total_rows=total_rows,
            valid_rows=valid_rows,
            format_failures=total_rows - valid_rows,
            answer_correct=answer_correct,
            decision_required=decision_required,
            decision_correct=decision_correct,
            missing_correct=missing_correct,
            evidence_precision_sum=evidence_precision_sum,
            evidence_recall_sum=evidence_recall_sum,
            evidence_f1_sum=evidence_f1_sum,
            unsupported_sum=unsupported_sum,
            counterfactual=counterfactual,
        )
    return ProtocolDataset(
        name=name,
        case_stats=case_stats,
        point_estimates=point_estimates,
        total_rows=sum(stat.total_rows for stat in case_stats.values()),
        case_ids=sorted(case_stats),
    )


def _build_case_stats_from_batched(
    *,
    report_path: str | Path,
    counterfactual_path: str | Path,
    point_estimates: dict[str, Any],
    name: str = "variant_batched_compact",
) -> ProtocolDataset:
    report = _load_json(report_path)
    records = report["records"]
    cf_rows = _load_json(counterfactual_path)["rows"]
    cf_by_case: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in cf_rows:
        cf_by_case[str(row["case_id"])][str(row["namespace"])].append(row)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[str(row["key"]["case_id"])].append(row)

    case_stats: dict[str, CaseStats] = {}
    for case_id in sorted(grouped):
        rows = grouped[case_id]
        total_rows = len(rows)
        valid_rows = len(rows)
        answer_correct = sum(1 for row in rows if row["answer_correct"])
        decision_required = sum(1 for row in rows if row["decision_required"])
        decision_correct = sum(1 for row in rows if row["decision_required"] and row["decision_correct"])
        missing_correct = sum(1 for row in rows if row["missing_information_correct"])
        evidence_precision_sum = sum(row["evidence_precision"] for row in rows)
        evidence_recall_sum = sum(row["evidence_recall"] for row in rows)
        evidence_f1_sum = sum(row["evidence_f1"] for row in rows)
        unsupported_sum = sum(row["unsupported_evidence_rate"] for row in rows)
        counterfactual = _summarize_case_counterfactual(case_id, cf_by_case.get(case_id, {}))
        case_stats[case_id] = CaseStats(
            case_id=case_id,
            total_rows=total_rows,
            valid_rows=valid_rows,
            format_failures=0,
            answer_correct=answer_correct,
            decision_required=decision_required,
            decision_correct=decision_correct,
            missing_correct=missing_correct,
            evidence_precision_sum=evidence_precision_sum,
            evidence_recall_sum=evidence_recall_sum,
            evidence_f1_sum=evidence_f1_sum,
            unsupported_sum=unsupported_sum,
            counterfactual=counterfactual,
        )
    return ProtocolDataset(
        name=name,
        case_stats=case_stats,
        point_estimates=point_estimates,
        total_rows=sum(stat.total_rows for stat in case_stats.values()),
        case_ids=sorted(case_stats),
    )


def _summarize_case_counterfactual(case_id: str, namespaces: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for namespace, rows in namespaces.items():
        strict_denom = len(rows)
        strict_num = sum(int(bool(row["score"])) for row in rows)
        valid_rows = [row for row in rows if row.get("valid_pair", True)]
        valid_denom = len(valid_rows)
        valid_num = sum(int(bool(row["score"])) for row in valid_rows)
        summary[namespace] = {
            "strict_numerator": float(strict_num),
            "strict_denominator": float(strict_denom),
            "strict_score": _safe_div(strict_num, strict_denom),
            "valid_numerator": float(valid_num),
            "valid_denominator": float(valid_denom),
            "valid_score": _safe_div(valid_num, valid_denom),
        }
    return summary


def _dataset_counterfactual_points(dataset: ProtocolDataset) -> dict[str, dict[str, float]]:
    points: dict[str, dict[str, float]] = {}
    for namespace in ["ab_flip", "ab_invariant", "ac_nuisance_flip", "ac_causal_invariant"]:
        strict_num = sum(stat.counterfactual.get(namespace, {}).get("strict_numerator", 0.0) for stat in dataset.case_stats.values())
        strict_den = sum(stat.counterfactual.get(namespace, {}).get("strict_denominator", 0.0) for stat in dataset.case_stats.values())
        valid_num = sum(stat.counterfactual.get(namespace, {}).get("valid_numerator", 0.0) for stat in dataset.case_stats.values())
        valid_den = sum(stat.counterfactual.get(namespace, {}).get("valid_denominator", 0.0) for stat in dataset.case_stats.values())
        is_flip = namespace in {"ab_flip", "ac_nuisance_flip"}
        points[namespace] = {
            "strict_numerator": strict_num,
            "strict_denominator": strict_den,
            "strict_score": _safe_div(strict_num, strict_den),
            "strict_missed_update_rate": _safe_div(strict_den - strict_num, strict_den) if is_flip else 0.0,
            "strict_over_update_rate": _safe_div(strict_den - strict_num, strict_den) if not is_flip else 0.0,
            "valid_numerator": valid_num,
            "valid_denominator": valid_den,
            "valid_score": _safe_div(valid_num, valid_den),
            "valid_missed_update_rate": _safe_div(valid_den - valid_num, valid_den) if is_flip else 0.0,
            "valid_over_update_rate": _safe_div(valid_den - valid_num, valid_den) if not is_flip else 0.0,
        }
    return points


def _dataset_overall_points(dataset: ProtocolDataset) -> dict[str, float]:
    total_rows = sum(stat.total_rows for stat in dataset.case_stats.values())
    valid_rows = sum(stat.valid_rows for stat in dataset.case_stats.values())
    decision_required = sum(stat.decision_required for stat in dataset.case_stats.values())
    answer_correct = sum(stat.answer_correct for stat in dataset.case_stats.values())
    decision_correct = sum(stat.decision_correct for stat in dataset.case_stats.values())
    missing_correct = sum(stat.missing_correct for stat in dataset.case_stats.values())
    evidence_precision_sum = sum(stat.evidence_precision_sum for stat in dataset.case_stats.values())
    evidence_recall_sum = sum(stat.evidence_recall_sum for stat in dataset.case_stats.values())
    evidence_f1_sum = sum(stat.evidence_f1_sum for stat in dataset.case_stats.values())
    unsupported_sum = sum(stat.unsupported_sum for stat in dataset.case_stats.values())
    return {
        "answer_accuracy": _safe_div(answer_correct, total_rows),
        "decision_accuracy": _safe_div(decision_correct, decision_required),
        "missing_information_accuracy": _safe_div(missing_correct, total_rows),
        "evidence_precision": _safe_div(evidence_precision_sum, total_rows),
        "evidence_recall": _safe_div(evidence_recall_sum, total_rows),
        "evidence_f1": _safe_div(evidence_f1_sum, total_rows),
        "unsupported_evidence_rate": _safe_div(unsupported_sum, total_rows),
        "format_success_rate": _safe_div(valid_rows, total_rows),
        "valid_rows": valid_rows,
        "total_rows": total_rows,
        "decision_required_count": decision_required,
    }


def load_independent_dataset(
    *,
    gold_path: str | Path,
    predictions_path: str | Path,
    counterfactual_path: str | Path,
    release_bundle_path: str | Path,
) -> ProtocolDataset:
    bundle = _load_json(release_bundle_path)
    dataset = _build_case_stats_from_independent(
        gold_path=gold_path,
        predictions_path=predictions_path,
        counterfactual_path=counterfactual_path,
        point_estimates=bundle["primary_metrics"]["strict_end_to_end"],
    )
    merged_points = {**bundle["primary_metrics"]["strict_end_to_end"], **_dataset_overall_points(dataset), "counterfactual": _dataset_counterfactual_points(dataset)}
    object.__setattr__(dataset, "point_estimates", merged_points)
    return dataset


def load_batched_dataset(
    *,
    report_path: str | Path,
    counterfactual_path: str | Path,
    compact_report_path: str | Path,
) -> ProtocolDataset:
    report = _load_json(compact_report_path)
    dataset = _build_case_stats_from_batched(
        report_path=report_path,
        counterfactual_path=counterfactual_path,
        point_estimates=report["overall"],
    )
    merged_points = {**report["overall"], **_dataset_overall_points(dataset), "counterfactual": _dataset_counterfactual_points(dataset)}
    object.__setattr__(dataset, "point_estimates", merged_points)
    return dataset


def sample_case_clusters(case_ids: Iterable[str], *, replicates: int, seed: int) -> list[tuple[str, ...]]:
    ids = list(case_ids)
    rng = random.Random(seed)
    return [tuple(rng.choice(ids) for _ in range(BOOTSTRAP_CASE_COUNT)) for _ in range(replicates)]


def _aggregate_case_stats(dataset: ProtocolDataset, sampled_case_ids: Iterable[str]) -> dict[str, Any]:
    totals = {
        "total_rows": 0,
        "valid_rows": 0,
        "format_failures": 0,
        "answer_correct": 0,
        "decision_required": 0,
        "decision_correct": 0,
        "missing_correct": 0,
        "evidence_precision_sum": 0.0,
        "evidence_recall_sum": 0.0,
        "evidence_f1_sum": 0.0,
        "unsupported_sum": 0.0,
    }
    counterfactual_totals: dict[str, dict[str, float]] = defaultdict(lambda: {
        "strict_numerator": 0.0,
        "strict_denominator": 0.0,
        "valid_numerator": 0.0,
        "valid_denominator": 0.0,
    })
    for case_id in sampled_case_ids:
        stats = dataset.case_stats[case_id]
        totals["total_rows"] += stats.total_rows
        totals["valid_rows"] += stats.valid_rows
        totals["format_failures"] += stats.format_failures
        totals["answer_correct"] += stats.answer_correct
        totals["decision_required"] += stats.decision_required
        totals["decision_correct"] += stats.decision_correct
        totals["missing_correct"] += stats.missing_correct
        totals["evidence_precision_sum"] += stats.evidence_precision_sum
        totals["evidence_recall_sum"] += stats.evidence_recall_sum
        totals["evidence_f1_sum"] += stats.evidence_f1_sum
        totals["unsupported_sum"] += stats.unsupported_sum
        for namespace, summary in stats.counterfactual.items():
            counterfactual_totals[namespace]["strict_numerator"] += summary["strict_numerator"]
            counterfactual_totals[namespace]["strict_denominator"] += summary["strict_denominator"]
            counterfactual_totals[namespace]["valid_numerator"] += summary["valid_numerator"]
            counterfactual_totals[namespace]["valid_denominator"] += summary["valid_denominator"]

    metrics = {
        "total_rows": totals["total_rows"],
        "valid_rows": totals["valid_rows"],
        "format_failures": totals["format_failures"],
        "format_success_rate": _safe_div(totals["valid_rows"], totals["total_rows"]),
        "answer_accuracy": _safe_div(totals["answer_correct"], totals["total_rows"]),
        "decision_accuracy": _safe_div(totals["decision_correct"], totals["decision_required"]),
        "missing_information_accuracy": _safe_div(totals["missing_correct"], totals["total_rows"]),
        "evidence_precision": _safe_div(totals["evidence_precision_sum"], totals["total_rows"]),
        "evidence_recall": _safe_div(totals["evidence_recall_sum"], totals["total_rows"]),
        "evidence_f1": _safe_div(totals["evidence_f1_sum"], totals["total_rows"]),
        "unsupported_evidence_rate": _safe_div(totals["unsupported_sum"], totals["total_rows"]),
        "decision_required_count": totals["decision_required"],
        "counterfactual": {},
    }
    for namespace, summary in counterfactual_totals.items():
        is_flip = namespace in {"ab_flip", "ac_nuisance_flip"}
        strict_score = _safe_div(summary["strict_numerator"], summary["strict_denominator"])
        valid_score = _safe_div(summary["valid_numerator"], summary["valid_denominator"])
        metrics["counterfactual"][namespace] = {
            "strict_numerator": summary["strict_numerator"],
            "strict_denominator": summary["strict_denominator"],
            "strict_score": strict_score,
            "strict_missed_update_rate": _safe_div(summary["strict_denominator"] - summary["strict_numerator"], summary["strict_denominator"]) if is_flip else 0.0,
            "strict_over_update_rate": _safe_div(summary["strict_denominator"] - summary["strict_numerator"], summary["strict_denominator"]) if not is_flip else 0.0,
            "valid_numerator": summary["valid_numerator"],
            "valid_denominator": summary["valid_denominator"],
            "valid_score": valid_score,
            "valid_missed_update_rate": _safe_div(summary["valid_denominator"] - summary["valid_numerator"], summary["valid_denominator"]) if is_flip else 0.0,
            "valid_over_update_rate": _safe_div(summary["valid_denominator"] - summary["valid_numerator"], summary["valid_denominator"]) if not is_flip else 0.0,
        }
    return metrics


def bootstrap_case_cluster_metrics(
    dataset: ProtocolDataset,
    samples: list[tuple[str, ...]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for replicate_id, sampled_case_ids in enumerate(samples):
        aggregate = _aggregate_case_stats(dataset, sampled_case_ids)
        row = {
            "replicate": replicate_id,
            "sampled_cases": "|".join(sampled_case_ids),
            "total_rows": aggregate["total_rows"],
            "valid_rows": aggregate["valid_rows"],
            "format_failures": aggregate["format_failures"],
            "format_success_rate": aggregate["format_success_rate"],
            "answer_accuracy": aggregate["answer_accuracy"],
            "decision_accuracy": aggregate["decision_accuracy"],
            "missing_information_accuracy": aggregate["missing_information_accuracy"],
            "evidence_precision": aggregate["evidence_precision"],
            "evidence_recall": aggregate["evidence_recall"],
            "evidence_f1": aggregate["evidence_f1"],
            "unsupported_evidence_rate": aggregate["unsupported_evidence_rate"],
            "decision_required_count": aggregate["decision_required_count"],
        }
        for namespace, summary in aggregate["counterfactual"].items():
            row[f"{namespace}_strict_score"] = summary["strict_score"]
            row[f"{namespace}_strict_numerator"] = summary["strict_numerator"]
            row[f"{namespace}_strict_denominator"] = summary["strict_denominator"]
            row[f"{namespace}_strict_missed_update_rate"] = summary["strict_missed_update_rate"]
            row[f"{namespace}_strict_over_update_rate"] = summary["strict_over_update_rate"]
            row[f"{namespace}_valid_score"] = summary["valid_score"]
            row[f"{namespace}_valid_numerator"] = summary["valid_numerator"]
            row[f"{namespace}_valid_denominator"] = summary["valid_denominator"]
            row[f"{namespace}_valid_missed_update_rate"] = summary["valid_missed_update_rate"]
            row[f"{namespace}_valid_over_update_rate"] = summary["valid_over_update_rate"]
        rows.append(row)
    return rows


def paired_protocol_effect(
    batched: ProtocolDataset,
    independent: ProtocolDataset,
    samples: list[tuple[str, ...]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for replicate_id, sampled_case_ids in enumerate(samples):
        batched_metrics = _aggregate_case_stats(batched, sampled_case_ids)
        independent_metrics = _aggregate_case_stats(independent, sampled_case_ids)
        row = {
            "replicate": replicate_id,
            "sampled_cases": "|".join(sampled_case_ids),
            "delta_answer": batched_metrics["answer_accuracy"] - independent_metrics["answer_accuracy"],
            "delta_decision": batched_metrics["decision_accuracy"] - independent_metrics["decision_accuracy"],
            "delta_evidence_f1": batched_metrics["evidence_f1"] - independent_metrics["evidence_f1"],
            "delta_format_success": batched_metrics["format_success_rate"] - independent_metrics["format_success_rate"],
        }
        for namespace in ["ab_flip", "ab_invariant", "ac_nuisance_flip", "ac_causal_invariant"]:
            row[f"delta_{namespace}"] = batched_metrics["counterfactual"].get(namespace, {}).get("strict_score", 0.0) - independent_metrics["counterfactual"].get(namespace, {}).get("strict_score", 0.0)
        rows.append(row)
    return rows


def summarize_metric_distributions(rows: list[dict[str, Any]], metric_names: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for metric in metric_names:
        values = [float(row[metric]) for row in rows]
        summary[metric] = {
            "point_estimate": values[0] if values else 0.0,
            "median": median(values) if values else 0.0,
            "ci_low": _percentile(values, 0.025),
            "ci_high": _percentile(values, 0.975),
            "p_gt_0": _safe_div(sum(1 for value in values if value > 0), len(values)),
        }
    return summary


def build_case_level_comparison(
    batched: ProtocolDataset,
    independent: ProtocolDataset,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_id in batched.case_ids:
        b = batched.case_stats[case_id]
        i = independent.case_stats[case_id]
        row = {
            "case_id": case_id,
            "total_rows": b.total_rows,
            "batched_answer_accuracy": _safe_div(b.answer_correct, b.total_rows),
            "independent_strict_answer_accuracy": _safe_div(i.answer_correct, i.total_rows),
            "delta_answer_accuracy": _safe_div(b.answer_correct, b.total_rows) - _safe_div(i.answer_correct, i.total_rows),
            "independent_format_failure_rate": _safe_div(i.format_failures, i.total_rows),
            "batched_evidence_f1": _safe_div(b.evidence_f1_sum, b.total_rows),
            "independent_strict_evidence_f1": _safe_div(i.evidence_f1_sum, i.total_rows),
            "batched_decision_accuracy": _safe_div(b.decision_correct, b.decision_required),
            "independent_strict_decision_accuracy": _safe_div(i.decision_correct, i.decision_required),
            "batched_format_success_rate": _safe_div(b.valid_rows, b.total_rows),
            "independent_format_success_rate": _safe_div(i.valid_rows, i.total_rows),
        }
        for namespace in ["ab_flip", "ab_invariant", "ac_nuisance_flip", "ac_causal_invariant"]:
            b_ns = b.counterfactual.get(namespace, {})
            i_ns = i.counterfactual.get(namespace, {})
            row[f"batched_{namespace}_strict_numerator"] = b_ns.get("strict_numerator", 0.0)
            row[f"batched_{namespace}_strict_denominator"] = b_ns.get("strict_denominator", 0.0)
            row[f"batched_{namespace}_strict_score"] = b_ns.get("strict_score", 0.0)
            row[f"batched_{namespace}_valid_numerator"] = b_ns.get("valid_numerator", 0.0)
            row[f"batched_{namespace}_valid_denominator"] = b_ns.get("valid_denominator", 0.0)
            row[f"batched_{namespace}_valid_score"] = b_ns.get("valid_score", 0.0)
            row[f"independent_{namespace}_strict_numerator"] = i_ns.get("strict_numerator", 0.0)
            row[f"independent_{namespace}_strict_denominator"] = i_ns.get("strict_denominator", 0.0)
            row[f"independent_{namespace}_strict_score"] = i_ns.get("strict_score", 0.0)
            row[f"independent_{namespace}_valid_numerator"] = i_ns.get("valid_numerator", 0.0)
            row[f"independent_{namespace}_valid_denominator"] = i_ns.get("valid_denominator", 0.0)
            row[f"independent_{namespace}_valid_score"] = i_ns.get("valid_score", 0.0)
        rows.append(row)
    return rows


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render_svg_bar_chart(
    *,
    width: int,
    height: int,
    title: str,
    subtitle: str,
    labels: list[str],
    series: list[tuple[str, list[float], str]],
    y_max: float,
) -> str:
    left = 80
    right = 20
    top = 80
    bottom = 120
    chart_width = width - left - right
    chart_height = height - top - bottom
    n = len(labels)
    group_width = chart_width / max(n, 1)
    series_count = max(len(series), 1)
    bar_gap = 0.12
    bar_width = group_width * (1 - bar_gap) / max(series_count, 1)
    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfaf7"/>',
        f'<text x="{left}" y="30" font-size="24" font-family="Arial, sans-serif" font-weight="700">{_escape(title)}</text>',
        f'<text x="{left}" y="52" font-size="14" font-family="Arial, sans-serif" fill="#555">{_escape(subtitle)}</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_height}" stroke="#222" stroke-width="1.5"/>',
        f'<line x1="{left}" y1="{top + chart_height}" x2="{left + chart_width}" y2="{top + chart_height}" stroke="#222" stroke-width="1.5"/>',
    ]
    for tick in range(6):
        value = y_max * tick / 5
        y = top + chart_height - (value / y_max if y_max else 0) * chart_height
        svg.append(f'<line x1="{left-4}" y1="{y:.2f}" x2="{left+4}" y2="{y:.2f}" stroke="#222" stroke-width="1"/>')
        svg.append(f'<text x="{left-8}" y="{y+4:.2f}" font-size="11" font-family="Arial, sans-serif" text-anchor="end" fill="#444">{value:.2f}</text>')
        svg.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + chart_width}" y2="{y:.2f}" stroke="#e7e1d7" stroke-width="1"/>')
    for idx, label in enumerate(labels):
        base_x = left + idx * group_width
        svg.append(f'<line x1="{base_x + group_width/2:.2f}" y1="{top + chart_height}" x2="{base_x + group_width/2:.2f}" y2="{top + chart_height + 4}" stroke="#222"/>')
        svg.append(
            f'<text x="{base_x + group_width/2:.2f}" y="{top + chart_height + 20}" font-size="11" font-family="Arial, sans-serif" text-anchor="middle" transform="rotate(45 {base_x + group_width/2:.2f},{top + chart_height + 20})">{_escape(label)}</text>'
        )
        for s_idx, (name, values, color) in enumerate(series):
            if idx >= len(values):
                continue
            value = values[idx]
            bar_height = (value / y_max if y_max else 0) * chart_height
            x = base_x + (group_width - bar_width * series_count) / 2 + s_idx * bar_width
            y = top + chart_height - bar_height
            svg.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width*0.92:.2f}" height="{bar_height:.2f}" fill="{color}" rx="2" ry="2"/>')
        svg.append(f'<text x="{base_x + group_width/2:.2f}" y="{top + chart_height + 55}" font-size="11" font-family="Arial, sans-serif" text-anchor="middle" fill="#555">{_escape(label)}</text>')
    legend_x = left + chart_width - 220
    legend_y = 60
    for i, (name, _, color) in enumerate(series):
        y = legend_y + i * 20
        svg.append(f'<rect x="{legend_x}" y="{y-10}" width="12" height="12" fill="{color}"/>')
        svg.append(f'<text x="{legend_x+18}" y="{y}" font-size="12" font-family="Arial, sans-serif" fill="#222">{_escape(name)}</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def render_svg_histogram(
    *,
    width: int,
    height: int,
    title: str,
    subtitle: str,
    values: list[float],
    bins: int = 40,
    color: str = "#3c6e71",
) -> str:
    if not values:
        values = [0.0]
    min_v = min(values)
    max_v = max(values)
    if math.isclose(min_v, max_v):
        min_v -= 1e-6
        max_v += 1e-6
    step = (max_v - min_v) / bins
    counts = [0] * bins
    for value in values:
        idx = min(bins - 1, max(0, int((value - min_v) / step)))
        counts[idx] += 1
    left = 80
    right = 20
    top = 80
    bottom = 80
    chart_width = width - left - right
    chart_height = height - top - bottom
    max_count = max(counts) if counts else 1
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfaf7"/>',
        f'<text x="{left}" y="30" font-size="24" font-family="Arial, sans-serif" font-weight="700">{_escape(title)}</text>',
        f'<text x="{left}" y="52" font-size="14" font-family="Arial, sans-serif" fill="#555">{_escape(subtitle)}</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_height}" stroke="#222" stroke-width="1.5"/>',
        f'<line x1="{left}" y1="{top + chart_height}" x2="{left + chart_width}" y2="{top + chart_height}" stroke="#222" stroke-width="1.5"/>',
    ]
    bar_width = chart_width / bins
    for i, count in enumerate(counts):
        h = (count / max_count) * chart_height if max_count else 0
        x = left + i * bar_width
        y = top + chart_height - h
        svg.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(bar_width-1,0.5):.2f}" height="{h:.2f}" fill="{color}" opacity="0.85"/>')
    for tick in range(6):
        value = min_v + (max_v - min_v) * tick / 5
        x = left + (value - min_v) / (max_v - min_v) * chart_width
        svg.append(f'<line x1="{x:.2f}" y1="{top + chart_height}" x2="{x:.2f}" y2="{top + chart_height + 5}" stroke="#222"/>')
        svg.append(f'<text x="{x:.2f}" y="{top + chart_height + 20}" font-size="11" font-family="Arial, sans-serif" text-anchor="middle" fill="#444">{value:.3f}</text>')
    svg.append(f'<text x="{left}" y="{height - 25}" font-size="12" font-family="Arial, sans-serif" fill="#555">n={len(values)} bins={bins}</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_svg(path: str | Path, svg: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")


def svg_to_png(svg_path: str | Path, png_path: str | Path) -> None:
    svg_path = Path(svg_path)
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["sips", "-s", "format", "png", str(svg_path), "--out", str(png_path)], check=True, capture_output=True, text=True)


def write_table_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    write_csv(path, rows, fieldnames)


def write_distribution_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    write_csv(path, rows, fieldnames)


def build_statistics_artifacts(
    *,
    gold_path: str | Path,
    independent_predictions_path: str | Path,
    independent_counterfactual_path: str | Path,
    independent_release_bundle_path: str | Path,
    batched_report_path: str | Path,
    batched_counterfactual_path: str | Path,
    batched_manifest_path: str | Path,
    output_dir: str | Path,
    seed: int = 42,
    replicates: int = 10_000,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    independent = load_independent_dataset(
        gold_path=gold_path,
        predictions_path=independent_predictions_path,
        counterfactual_path=independent_counterfactual_path,
        release_bundle_path=independent_release_bundle_path,
    )
    batched = load_batched_dataset(
        report_path=batched_report_path,
        counterfactual_path=batched_counterfactual_path,
        compact_report_path=batched_report_path,
    )

    samples = sample_case_clusters(independent.case_ids, replicates=replicates, seed=seed)
    bootstrap_rows = bootstrap_case_cluster_metrics(independent, samples)
    paired_rows = paired_protocol_effect(batched, independent, samples)

    metric_names = [
        "answer_accuracy",
        "decision_accuracy",
        "missing_information_accuracy",
        "evidence_precision",
        "evidence_recall",
        "evidence_f1",
        "format_success_rate",
        "ab_flip_strict_score",
        "ab_invariant_strict_score",
        "ac_nuisance_flip_strict_score",
        "ac_causal_invariant_strict_score",
        "ab_flip_strict_missed_update_rate",
        "ab_invariant_strict_over_update_rate",
        "ac_nuisance_flip_strict_missed_update_rate",
        "ac_causal_invariant_strict_over_update_rate",
    ]

    bootstrap_summary = {
        "seed": seed,
        "replicates": replicates,
        "case_clusters": len(independent.case_ids),
        "point_estimates": {
            "answer_accuracy": independent.point_estimates["answer_accuracy"],
            "decision_accuracy": independent.point_estimates["decision_accuracy"],
            "missing_information_accuracy": independent.point_estimates["missing_information_accuracy"],
            "evidence_precision": independent.point_estimates["evidence_precision"],
            "evidence_recall": independent.point_estimates["evidence_recall"],
            "evidence_f1": independent.point_estimates["evidence_f1"],
            "format_success_rate": _safe_div(sum(stat.valid_rows for stat in independent.case_stats.values()), sum(stat.total_rows for stat in independent.case_stats.values())),
            "counterfactual": {
                namespace: {
                    "strict_score": _safe_div(
                        sum(stat.counterfactual.get(namespace, {}).get("strict_numerator", 0.0) for stat in independent.case_stats.values()),
                        sum(stat.counterfactual.get(namespace, {}).get("strict_denominator", 0.0) for stat in independent.case_stats.values()),
                    ),
                    "strict_denominator": sum(stat.counterfactual.get(namespace, {}).get("strict_denominator", 0.0) for stat in independent.case_stats.values()),
                }
                for namespace in ["ab_flip", "ab_invariant", "ac_nuisance_flip", "ac_causal_invariant"]
            },
        },
        "bootstrap": {},
    }
    for metric in metric_names:
        if metric not in bootstrap_rows[0]:
            continue
        values = [row[metric] for row in bootstrap_rows]
        if metric == "answer_accuracy":
            point = independent.point_estimates["answer_accuracy"]
        elif metric == "decision_accuracy":
            point = independent.point_estimates["decision_accuracy"]
        elif metric == "missing_information_accuracy":
            point = independent.point_estimates["missing_information_accuracy"]
        elif metric == "evidence_precision":
            point = independent.point_estimates["evidence_precision"]
        elif metric == "evidence_recall":
            point = independent.point_estimates["evidence_recall"]
        elif metric == "evidence_f1":
            point = independent.point_estimates["evidence_f1"]
        elif metric == "format_success_rate":
            point = _safe_div(sum(stat.valid_rows for stat in independent.case_stats.values()), sum(stat.total_rows for stat in independent.case_stats.values()))
        elif metric.endswith("_strict_score"):
            namespace = metric.removesuffix("_strict_score")
            point = independent.point_estimates["counterfactual"][namespace]["strict_score"]
        elif metric.endswith("_strict_missed_update_rate"):
            namespace = metric.removesuffix("_strict_missed_update_rate")
            point = independent.point_estimates["counterfactual"][namespace]["strict_missed_update_rate"]
        elif metric.endswith("_strict_over_update_rate"):
            namespace = metric.removesuffix("_strict_over_update_rate")
            point = independent.point_estimates["counterfactual"][namespace]["strict_over_update_rate"]
        elif metric.endswith("_valid_score"):
            namespace = metric.removesuffix("_valid_score")
            point = independent.point_estimates["counterfactual"][namespace]["valid_score"]
        elif metric.endswith("_valid_missed_update_rate"):
            namespace = metric.removesuffix("_valid_missed_update_rate")
            point = independent.point_estimates["counterfactual"][namespace]["valid_missed_update_rate"]
        elif metric.endswith("_valid_over_update_rate"):
            namespace = metric.removesuffix("_valid_over_update_rate")
            point = independent.point_estimates["counterfactual"][namespace]["valid_over_update_rate"]
        else:
            point = 0.0
        bootstrap_summary["bootstrap"][metric] = _bootstrap_summary(values, point_estimate=point)

    effect_metrics = {
        "delta_answer",
        "delta_decision",
        "delta_evidence_f1",
        "delta_format_success",
        "delta_ab_flip",
        "delta_ab_invariant",
        "delta_ac_nuisance_flip",
        "delta_ac_causal_invariant",
    }
    protocol_effect_summary = {
        "seed": seed,
        "replicates": replicates,
        "case_clusters": len(independent.case_ids),
        "batched_point_estimates": {
            "answer_accuracy": batched.point_estimates["answer_accuracy"],
            "decision_accuracy": batched.point_estimates["decision_accuracy"],
            "evidence_f1": batched.point_estimates["evidence_f1"],
            "format_success_rate": 1.0,
        },
        "independent_point_estimates": {
            "answer_accuracy": independent.point_estimates["answer_accuracy"],
            "decision_accuracy": independent.point_estimates["decision_accuracy"],
            "evidence_f1": independent.point_estimates["evidence_f1"],
            "format_success_rate": _safe_div(sum(stat.valid_rows for stat in independent.case_stats.values()), sum(stat.total_rows for stat in independent.case_stats.values())),
        },
        "delta_point_estimates": {
            "delta_answer": batched.point_estimates["answer_accuracy"] - independent.point_estimates["answer_accuracy"],
            "delta_decision": batched.point_estimates["decision_accuracy"] - independent.point_estimates["decision_accuracy"],
            "delta_evidence_f1": batched.point_estimates["evidence_f1"] - independent.point_estimates["evidence_f1"],
            "delta_format_success": 1.0 - _safe_div(sum(stat.valid_rows for stat in independent.case_stats.values()), sum(stat.total_rows for stat in independent.case_stats.values())),
        },
        "bootstrap": {},
    }
    for metric in effect_metrics:
        values = [row[metric] for row in paired_rows]
        if metric == "delta_answer":
            point = batched.point_estimates["answer_accuracy"] - independent.point_estimates["answer_accuracy"]
        elif metric == "delta_decision":
            point = batched.point_estimates["decision_accuracy"] - independent.point_estimates["decision_accuracy"]
        elif metric == "delta_evidence_f1":
            point = batched.point_estimates["evidence_f1"] - independent.point_estimates["evidence_f1"]
        elif metric == "delta_format_success":
            point = 1.0 - _safe_div(sum(stat.valid_rows for stat in independent.case_stats.values()), sum(stat.total_rows for stat in independent.case_stats.values()))
        else:
            namespace = metric.removeprefix("delta_")
            point = batched.point_estimates.get("counterfactual", {}).get(namespace, {}).get("strict_score", 0.0) - independent.point_estimates.get("counterfactual", {}).get(namespace, {}).get("strict_score", 0.0)
        protocol_effect_summary["bootstrap"][metric] = _bootstrap_summary(values, point_estimate=point)

    # case-level comparison
    case_rows = build_case_level_comparison(batched, independent)

    # export CSVs
    stats_dir = output_dir / "statistics"
    stats_dir.mkdir(parents=True, exist_ok=True)
    write_json(stats_dir / "qwen3.5-4b_case_bootstrap_summary.json", bootstrap_summary)
    write_json(stats_dir / "qwen3.5-4b_protocol_effect_summary.json", protocol_effect_summary)
    write_table_csv(
        stats_dir / "qwen3.5-4b_case_level_comparison.csv",
        case_rows,
        list(case_rows[0].keys()),
    )
    write_distribution_csv(
        stats_dir / "qwen3.5-4b_case_bootstrap_distributions.csv",
        bootstrap_rows,
        ["replicate", "sampled_cases", "total_rows", "valid_rows", "format_failures", "format_success_rate", "answer_accuracy", "decision_accuracy", "missing_information_accuracy", "evidence_precision", "evidence_recall", "evidence_f1", "unsupported_evidence_rate", "decision_required_count"]
        + [f"{namespace}_{suffix}" for namespace in ["ab_flip", "ab_invariant", "ac_nuisance_flip", "ac_causal_invariant"] for suffix in ["strict_score", "strict_numerator", "strict_denominator", "strict_missed_update_rate", "strict_over_update_rate", "valid_score", "valid_numerator", "valid_denominator", "valid_missed_update_rate", "valid_over_update_rate"]],
    )
    write_distribution_csv(
        stats_dir / "qwen3.5-4b_protocol_effect_distributions.csv",
        paired_rows,
        ["replicate", "sampled_cases", "delta_answer", "delta_decision", "delta_evidence_f1", "delta_format_success", "delta_ab_flip", "delta_ab_invariant", "delta_ac_nuisance_flip", "delta_ac_causal_invariant"],
    )

    # charts
    batched_answer = [batched.case_stats[c].answer_correct / batched.case_stats[c].total_rows for c in batched.case_ids]
    independent_answer = [independent.case_stats[c].answer_correct / independent.case_stats[c].total_rows for c in independent.case_ids]
    format_failure_rates = [independent.case_stats[c].format_failures / independent.case_stats[c].total_rows for c in independent.case_ids]
    delta_values = [row["delta_answer"] for row in paired_rows]
    namespace_labels = ["ab_flip", "ab_invariant", "ac_nuisance_flip", "ac_causal_invariant"]
    strict_scores = [
        _safe_div(
            sum(independent.case_stats[c].counterfactual.get(ns, {}).get("strict_numerator", 0.0) for c in independent.case_ids),
            sum(independent.case_stats[c].counterfactual.get(ns, {}).get("strict_denominator", 0.0) for c in independent.case_ids),
        )
        for ns in namespace_labels
    ]
    valid_scores = [
        _safe_div(
            sum(independent.case_stats[c].counterfactual.get(ns, {}).get("valid_numerator", 0.0) for c in independent.case_ids),
            sum(independent.case_stats[c].counterfactual.get(ns, {}).get("valid_denominator", 0.0) for c in independent.case_ids),
        )
        for ns in namespace_labels
    ]
    eval_counts = [
        int(sum(independent.case_stats[c].counterfactual.get(ns, {}).get("strict_denominator", 0.0) for c in independent.case_ids))
        for ns in namespace_labels
    ]
    valid_eval_counts = [
        int(sum(independent.case_stats[c].counterfactual.get(ns, {}).get("valid_denominator", 0.0) for c in independent.case_ids))
        for ns in namespace_labels
    ]
    counterfactual_labels = [
        f"{ns} (strict {strict_n}, valid {valid_n})"
        for ns, strict_n, valid_n in zip(namespace_labels, eval_counts, valid_eval_counts, strict=False)
    ]

    chart_specs = [
        (
            "batched_vs_independent_answer_accuracy",
            render_svg_bar_chart(
                width=1800,
                height=900,
                title="Batched vs independent answer accuracy by case",
                subtitle="Batched compact versus independent strict end-to-end",
                labels=batched.case_ids,
                series=[
                    ("batched", batched_answer, "#2a9d8f"),
                    ("independent", independent_answer, "#e76f51"),
                ],
                y_max=1.0,
            ),
        ),
        (
            "delta_answer_accuracy_distribution",
            render_svg_histogram(
                width=1200,
                height=800,
                title="Bootstrap distribution for delta answer accuracy",
                subtitle="Batched compact minus independent strict end-to-end",
                values=delta_values,
                bins=40,
                color="#457b9d",
            ),
        ),
        (
            "independent_format_failure_rate_by_case",
            render_svg_bar_chart(
                width=1800,
                height=900,
                title="Independent format failure rate by case",
                subtitle="Strict end-to-end format failures / total rows",
                labels=independent.case_ids,
                series=[("format failure rate", format_failure_rates, "#8d99ae")],
                y_max=1.0,
            ),
        ),
        (
            "counterfactual_strict_vs_valid_pair_scores",
            render_svg_bar_chart(
                width=1200,
                height=800,
                title="Strict and valid-pair counterfactual scores",
                subtitle="Bars show scores; evaluable pair counts are in the release JSON and CSV",
                labels=counterfactual_labels,
                series=[
                    ("strict", strict_scores, "#264653"),
                    ("valid-pair", valid_scores, "#e9c46a"),
                ],
                y_max=1.0,
            ),
        ),
    ]

    chart_paths: dict[str, dict[str, str]] = {}
    for stem, svg in chart_specs:
        svg_path = stats_dir / f"{stem}.svg"
        png_path = stats_dir / f"{stem}.png"
        write_svg(svg_path, svg)
        svg_to_png(svg_path, png_path)
        chart_paths[stem] = {"svg": str(svg_path), "png": str(png_path)}

    summary = {
        "seed": seed,
        "replicates": replicates,
        "case_clusters": len(independent.case_ids),
        "independent_release_bundle": str(independent_release_bundle_path),
        "batched_report": str(batched_report_path),
        "case_bootstrap_summary": str(stats_dir / "qwen3.5-4b_case_bootstrap_summary.json"),
        "case_bootstrap_distributions": str(stats_dir / "qwen3.5-4b_case_bootstrap_distributions.csv"),
        "protocol_effect_summary": str(stats_dir / "qwen3.5-4b_protocol_effect_summary.json"),
        "protocol_effect_distributions": str(stats_dir / "qwen3.5-4b_protocol_effect_distributions.csv"),
        "case_level_comparison": str(stats_dir / "qwen3.5-4b_case_level_comparison.csv"),
        "charts": chart_paths,
    }
    write_json(stats_dir / "qwen3.5-4b_statistics_manifest.json", summary)
    summary["manifest"] = str(stats_dir / "qwen3.5-4b_statistics_manifest.json")
    return summary
