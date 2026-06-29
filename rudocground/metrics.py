from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .io import DataFormatError, ensure_all_gold_present, load_gold, load_predictions, load_predictions_with_issues
from .models import (
    GoldRecord,
    PredictionRecord,
    normalize_answer_value,
    normalize_evidence,
    normalize_evidence_doc_ids,
)


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _set_metrics(predicted: tuple[str, ...], gold: tuple[str, ...]) -> dict[str, float]:
    pred_set = set(predicted)
    gold_set = set(gold)
    if not pred_set and not gold_set:
        return {
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
            "unsupported_rate": 0.0,
        }
    tp = len(pred_set & gold_set)
    precision = _safe_div(tp, len(pred_set))
    recall = _safe_div(tp, len(gold_set))
    f1 = _safe_div(2 * precision * recall, precision + recall)
    unsupported_rate = _safe_div(len(pred_set - gold_set), len(pred_set))
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "unsupported_rate": unsupported_rate,
    }


def _is_contaminated(record: PredictionRecord) -> bool:
    return bool((record.model_extra or {}).get("evaluation_contaminated"))


@dataclass
class EvaluationResult:
    overall: dict[str, Any]
    by_answer_type: dict[str, dict[str, Any]]
    counterfactual: dict[str, Any]
    records: list[dict[str, Any]]


@dataclass
class EvaluationReport(EvaluationResult):
    issues: list[dict[str, Any]]


def _evaluate_record(gold: GoldRecord, pred: PredictionRecord) -> dict[str, Any]:
    gold_answer = normalize_answer_value(gold.answer_type, gold.answer_normalized)
    if pred.answer_normalized is None:
        pred_answer = None
        answer_error = None
    else:
        try:
            pred_answer = normalize_answer_value(gold.answer_type, pred.answer_normalized)
            answer_error = None
        except ValueError as exc:
            pred_answer = None
            answer_error = str(exc)
    gold_supporting = normalize_evidence_doc_ids(gold.required_evidence or gold.supporting_evidence)
    pred_supporting = normalize_evidence_doc_ids(pred.required_evidence or pred.supporting_evidence)
    gold_missing = set(normalize_evidence(gold.missing_information))
    pred_missing = set(normalize_evidence(pred.missing_information))
    evidence_metrics = _set_metrics(pred_supporting, gold_supporting)
    if not gold.decision_required:
        decision_correct: bool | None = None
    else:
        decision_correct = pred.decision == gold.decision
    return {
        "key": {"case_id": gold.case_id, "variant_id": gold.variant_id, "question_id": gold.question_id},
        "answer_type": gold.answer_type,
        "decision_required": gold.decision_required,
        "answer_correct": pred_answer == gold_answer,
        "decision_correct": decision_correct,
        "missing_information_correct": pred_missing == gold_missing,
        "evidence_precision": evidence_metrics["precision"],
        "evidence_recall": evidence_metrics["recall"],
        "evidence_f1": evidence_metrics["f1"],
        "unsupported_evidence_rate": evidence_metrics["unsupported_rate"],
        "answer_error": answer_error,
    }


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(records)
    answer_accuracy = _safe_div(sum(1 for r in records if r["answer_correct"]), count)
    decision_records = [r for r in records if r.get("decision_required")]
    decision_accuracy = _safe_div(sum(1 for r in decision_records if r["decision_correct"]), len(decision_records))
    missing_accuracy = _safe_div(sum(1 for r in records if r["missing_information_correct"]), count)
    evidence_precision = _safe_div(sum(r["evidence_precision"] for r in records), count)
    evidence_recall = _safe_div(sum(r["evidence_recall"] for r in records), count)
    evidence_f1 = _safe_div(sum(r["evidence_f1"] for r in records), count)
    unsupported_rate = _safe_div(sum(r["unsupported_evidence_rate"] for r in records), count)
    return {
        "count": count,
        "answer_accuracy": answer_accuracy,
        "decision_accuracy": decision_accuracy,
        "decision_required_count": len(decision_records),
        "evidence_precision": evidence_precision,
        "evidence_recall": evidence_recall,
        "evidence_f1": evidence_f1,
        "missing_information_accuracy": missing_accuracy,
        "unsupported_evidence_rate": unsupported_rate,
    }


def _safe_normalize_answer(answer_type: str, value: Any) -> Any:
    try:
        return normalize_answer_value(answer_type, value)
    except ValueError:
        return None


def _pair_score(expected_change: bool, left_answer: Any, right_answer: Any) -> float:
    return 1.0 if ((left_answer != right_answer) if expected_change else (left_answer == right_answer)) else 0.0


def _summarize_counterfactual_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["namespace"])].append(row)
    summary: dict[str, dict[str, Any]] = {}
    for namespace, items in sorted(grouped.items()):
        numerator = int(round(sum(row["score"] for row in items)))
        denominator = len(items)
        error_count = denominator - numerator
        is_flip = namespace.endswith("flip")
        summary[namespace] = {
            "namespace": namespace,
            "numerator": numerator,
            "denominator": denominator,
            "score": _safe_div(numerator, denominator),
            "error_count": error_count,
            "error_rate": _safe_div(error_count, denominator),
            "missed_update_count": error_count if is_flip else 0,
            "missed_update_rate": _safe_div(error_count, denominator) if is_flip else 0.0,
            "over_update_count": error_count if not is_flip else 0,
            "over_update_rate": _safe_div(error_count, denominator) if not is_flip else 0.0,
        }
    return summary


def _aggregate_counterfactual_namespaces(summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    flip_namespaces = ("ab_flip", "ac_nuisance_flip")
    invariant_namespaces = ("ab_invariant", "ac_causal_invariant")
    flip_numerator = sum(summary[name]["numerator"] for name in flip_namespaces if name in summary)
    flip_denominator = sum(summary[name]["denominator"] for name in flip_namespaces if name in summary)
    invariant_numerator = sum(summary[name]["numerator"] for name in invariant_namespaces if name in summary)
    invariant_denominator = sum(summary[name]["denominator"] for name in invariant_namespaces if name in summary)
    missed_update_numerator = flip_denominator - flip_numerator
    over_update_numerator = invariant_denominator - invariant_numerator
    return {
        "ab_flip_score": summary.get("ab_flip", {}).get("score", 0.0),
        "ab_invariance_score": summary.get("ab_invariant", {}).get("score", 0.0),
        "ac_nuisance_detection_score": summary.get("ac_nuisance_flip", {}).get("score", 0.0),
        "ac_causal_invariance_score": summary.get("ac_causal_invariant", {}).get("score", 0.0),
        "ab_flip_numerator": summary.get("ab_flip", {}).get("numerator", 0),
        "ab_flip_denominator": summary.get("ab_flip", {}).get("denominator", 0),
        "ab_invariance_numerator": summary.get("ab_invariant", {}).get("numerator", 0),
        "ab_invariance_denominator": summary.get("ab_invariant", {}).get("denominator", 0),
        "ac_nuisance_detection_numerator": summary.get("ac_nuisance_flip", {}).get("numerator", 0),
        "ac_nuisance_detection_denominator": summary.get("ac_nuisance_flip", {}).get("denominator", 0),
        "ac_causal_invariance_numerator": summary.get("ac_causal_invariant", {}).get("numerator", 0),
        "ac_causal_invariance_denominator": summary.get("ac_causal_invariant", {}).get("denominator", 0),
        "missed_update_numerator": missed_update_numerator,
        "missed_update_denominator": flip_denominator,
        "missed_update_rate": _safe_div(missed_update_numerator, flip_denominator),
        "over_update_numerator": over_update_numerator,
        "over_update_denominator": invariant_denominator,
        "over_update_rate": _safe_div(over_update_numerator, invariant_denominator),
    }


def _legacy_counterfactual_scores(
    gold_records: list[GoldRecord],
    pred_records: dict[tuple[str, str, str], PredictionRecord],
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[GoldRecord]] = defaultdict(list)
    for record in gold_records:
        grouped[(record.case_id, record.question_id)].append(record)

    flip_scores = []
    invariance_scores = []
    rows = []
    for group_key, group in grouped.items():
        if len(group) != 2:
            continue
        left, right = sorted(group, key=lambda r: r.variant_id)
        left_pred = pred_records.get(left.key())
        right_pred = pred_records.get(right.key())
        if left_pred is None or right_pred is None:
            continue
        left_answer = _safe_normalize_answer(left.answer_type, left_pred.answer_normalized)
        right_answer = _safe_normalize_answer(right.answer_type, right_pred.answer_normalized)
        expected_change = left.must_change_from_other_variant or right.must_change_from_other_variant
        score = _pair_score(expected_change, left_answer, right_answer)
        rows.append(
            {
                "case_id": group_key[0],
                "question_id": group_key[1],
                "namespace": "legacy_ab_flip" if expected_change else "legacy_ab_invariant",
                "expected_relation": "flip" if expected_change else "invariant",
                "expected_change": expected_change,
                "left_variant": left.variant_id,
                "right_variant": right.variant_id,
                "left_answer": left_answer,
                "right_answer": right_answer,
                "score": score,
            }
        )
        if expected_change:
            flip_scores.append(score)
        else:
            invariance_scores.append(score)

    return {
        "legacy": {
            "flip_score": _safe_div(sum(flip_scores), len(flip_scores)),
            "invariance_score": _safe_div(sum(invariance_scores), len(invariance_scores)),
            "rows": rows,
            "flip_count": len(flip_scores),
            "invariance_count": len(invariance_scores),
        }
    }


def _full_counterfactual_rows(
    gold_records: list[GoldRecord],
    pred_records: dict[tuple[str, str, str], PredictionRecord],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, GoldRecord]] = defaultdict(dict)
    for record in gold_records:
        if record.variant_id in {"A", "B", "C"}:
            grouped[(record.case_id, record.question_id)][record.variant_id] = record

    rows: list[dict[str, Any]] = []
    for (case_id, question_id), variants in grouped.items():
        if {"A", "B", "C"} - set(variants):
            continue
        a = variants["A"]
        b = variants["B"]
        c = variants["C"]
        a_gold = normalize_answer_value(a.answer_type, a.answer_normalized)
        b_gold = normalize_answer_value(b.answer_type, b.answer_normalized)
        c_gold = normalize_answer_value(c.answer_type, c.answer_normalized)

        a_pred = _safe_normalize_answer(a.answer_type, pred_records[a.key()].answer_normalized) if a.key() in pred_records else None
        b_pred = _safe_normalize_answer(b.answer_type, pred_records[b.key()].answer_normalized) if b.key() in pred_records else None
        c_pred = _safe_normalize_answer(c.answer_type, pred_records[c.key()].answer_normalized) if c.key() in pred_records else None

        ab_expected_change = a_gold != b_gold
        ab_score = _pair_score(ab_expected_change, a_pred, b_pred)
        rows.append(
            {
                "case_id": case_id,
                "question_id": question_id,
                "namespace": "ab_flip" if ab_expected_change else "ab_invariant",
                "expected_relation": "flip" if ab_expected_change else "invariant",
                "expected_change": ab_expected_change,
                "left_variant": "A",
                "right_variant": "B",
                "left_answer": a_pred,
                "right_answer": b_pred,
                "gold_left_answer": a_gold,
                "gold_right_answer": b_gold,
                "score": ab_score,
            }
        )

        ac_expected_change = a_gold != c_gold
        if ab_expected_change and ac_expected_change:
            continue
        ac_namespace = "ac_nuisance_flip" if (not ab_expected_change and ac_expected_change) else "ac_causal_invariant"
        ac_score = _pair_score(ac_expected_change, a_pred, c_pred)
        rows.append(
            {
                "case_id": case_id,
                "question_id": question_id,
                "namespace": ac_namespace,
                "expected_relation": "nuisance_flip" if ac_namespace == "ac_nuisance_flip" else "causal_invariant",
                "expected_change": ac_expected_change,
                "left_variant": "A",
                "right_variant": "C",
                "left_answer": a_pred,
                "right_answer": c_pred,
                "gold_left_answer": a_gold,
                "gold_right_answer": c_gold,
                "score": ac_score,
            }
        )
    return rows


def _counterfactual_scores(gold_records: list[GoldRecord], pred_records: dict[tuple[str, str, str], PredictionRecord]) -> dict[str, Any]:
    full_rows = _full_counterfactual_rows(gold_records, pred_records)
    if full_rows:
        summary = _summarize_counterfactual_rows(full_rows)
        payload: dict[str, Any] = {
            "rows": full_rows,
            "namespaces": summary,
            **summary,
            **_aggregate_counterfactual_namespaces(summary),
        }
        payload["flip_score"] = payload["ab_flip_score"]
        payload["invariance_score"] = payload["ab_invariance_score"]
        payload["flip_count"] = payload["ab_flip_numerator"]
        payload["invariance_count"] = payload["ab_invariance_numerator"]
        legacy = _legacy_counterfactual_scores(gold_records, pred_records)
        if legacy["legacy"]["rows"]:
            payload.update(legacy)
        return payload
    legacy = _legacy_counterfactual_scores(gold_records, pred_records)
    legacy_payload = legacy["legacy"]
    return {
        "rows": legacy_payload["rows"],
        "namespaces": {
            "legacy_ab_flip": {
                "namespace": "legacy_ab_flip",
                "numerator": legacy_payload["flip_count"],
                "denominator": legacy_payload["flip_count"] + legacy_payload["invariance_count"],
                "score": legacy_payload["flip_score"],
                "error_count": 0,
                "error_rate": 0.0,
                "missed_update_count": 0,
                "missed_update_rate": 0.0,
                "over_update_count": 0,
                "over_update_rate": 0.0,
            },
            "legacy_ab_invariant": {
                "namespace": "legacy_ab_invariant",
                "numerator": legacy_payload["invariance_count"],
                "denominator": legacy_payload["flip_count"] + legacy_payload["invariance_count"],
                "score": legacy_payload["invariance_score"],
                "error_count": 0,
                "error_rate": 0.0,
                "missed_update_count": 0,
                "missed_update_rate": 0.0,
                "over_update_count": 0,
                "over_update_rate": 0.0,
            },
        },
        "legacy": legacy_payload,
        "flip_score": legacy_payload["flip_score"],
        "invariance_score": legacy_payload["invariance_score"],
        "flip_count": legacy_payload["flip_count"],
        "invariance_count": legacy_payload["invariance_count"],
    }


def evaluate(gold_path: str, predictions_path: str) -> EvaluationResult:
    gold = load_gold(gold_path)
    predictions = load_predictions(predictions_path)
    ensure_all_gold_present(gold, predictions)

    rows = []
    by_answer_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key, gold_record in gold.by_key.items():
        pred_record = predictions.by_key[key]
        if _is_contaminated(pred_record):
            continue
        row = _evaluate_record(gold_record, pred_record)
        rows.append(row)
        by_answer_type[gold_record.answer_type].append(row)

    overall = _aggregate(rows)
    typed = {answer_type: _aggregate(items) for answer_type, items in sorted(by_answer_type.items())}
    cf = _counterfactual_scores(list(gold.records), predictions.by_key)
    return EvaluationResult(overall=overall, by_answer_type=typed, counterfactual=cf, records=rows)


def evaluate_report(gold_path: str, predictions_path: str) -> EvaluationReport:
    gold = load_gold(gold_path)
    prediction_report = load_predictions_with_issues(predictions_path)
    predictions = prediction_report.dataset
    issues = [
        {"lineno": issue.lineno, "kind": issue.kind, "message": issue.message}
        for issue in prediction_report.issues
    ]

    rows = []
    by_answer_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    matched_keys = set()
    for key, gold_record in gold.by_key.items():
        pred_record = predictions.by_key.get(key)
        if pred_record is None:
            issues.append(
                {
                    "lineno": None,
                    "kind": "missing_prediction",
                    "message": f"missing prediction for {key}",
                }
            )
            continue
        if _is_contaminated(pred_record):
            issues.append(
                {
                    "lineno": None,
                    "kind": "contaminated_prediction",
                    "message": f"contaminated prediction skipped for {key}",
                }
            )
            continue
        matched_keys.add(key)
        row = _evaluate_record(gold_record, pred_record)
        rows.append(row)
        if row["answer_error"] is not None:
            issues.append(
                {
                    "lineno": None,
                    "kind": "invalid_answer",
                    "message": f"{key}: {row['answer_error']}",
                }
            )
        by_answer_type[gold_record.answer_type].append(row)

    extra_keys = sorted(set(predictions.by_key) - set(gold.by_key))
    for key in extra_keys:
        issues.append(
            {
                "lineno": None,
                "kind": "extra_prediction",
                "message": f"prediction without gold match for {key}",
            }
        )

    overall = _aggregate(rows)
    typed = {answer_type: _aggregate(items) for answer_type, items in sorted(by_answer_type.items())}
    cf = _counterfactual_scores(list(gold.records), {key: predictions.by_key[key] for key in matched_keys})
    return EvaluationReport(overall=overall, by_answer_type=typed, counterfactual=cf, records=rows, issues=issues)
