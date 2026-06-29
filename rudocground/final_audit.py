from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import csv
import json

from .io import load_gold
from .models import normalize_answer_value, normalize_evidence, normalize_evidence_doc_ids


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{lineno}: jsonl row is not an object")
            rows.append(row)
    return rows


@dataclass(frozen=True)
class TerminalPredictionJournal:
    rows: list[dict[str, Any]]
    by_key: dict[tuple[str, str, str], dict[str, Any]]
    attempts_by_key: dict[tuple[str, str, str], int]
    total_rows: int


def load_terminal_predictions(path: str | Path) -> TerminalPredictionJournal:
    rows = _load_jsonl(path)
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    attempts: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in rows:
        key = (str(row["case_id"]), str(row["variant_id"]), str(row["question_id"]))
        attempts[key] += 1
        by_key[key] = row
    return TerminalPredictionJournal(rows=rows, by_key=by_key, attempts_by_key=attempts, total_rows=len(rows))


def _safe_normalize_answer(answer_type: str, value: Any) -> Any:
    try:
        return normalize_answer_value(answer_type, value)
    except Exception:
        return None


def _row_evidence_metrics(gold_row: Any, pred_row: dict[str, Any], valid_row: bool) -> dict[str, float]:
    if not valid_row:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "unsupported_rate": 0.0}
    gold_supporting = normalize_evidence_doc_ids(gold_row.required_evidence or gold_row.supporting_evidence)
    pred_supporting = normalize_evidence_doc_ids(pred_row.get("evidence") or pred_row.get("supporting_evidence"))
    gold_set = set(gold_supporting)
    pred_set = set(pred_supporting)
    if not pred_set and not gold_set:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "unsupported_rate": 0.0}
    true_positive = len(pred_set & gold_set)
    precision = _safe_div(true_positive, len(pred_set))
    recall = _safe_div(true_positive, len(gold_set))
    f1 = _safe_div(2 * precision * recall, precision + recall)
    unsupported_rate = _safe_div(len(pred_set - gold_set), len(pred_set))
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "unsupported_rate": unsupported_rate,
    }


def _build_row_record(gold_row: Any, pred_row: dict[str, Any], *, strict: bool) -> dict[str, Any]:
    valid_row = pred_row.get("status") == "ok" and not bool(pred_row.get("evaluation_contaminated"))
    answer_type = gold_row.answer_type

    gold_answer = normalize_answer_value(answer_type, gold_row.answer_normalized)
    pred_answer = _safe_normalize_answer(answer_type, pred_row.get("answer")) if valid_row else None
    answer_correct = valid_row and pred_answer == gold_answer

    if gold_row.decision_required:
        decision_correct = valid_row and pred_row.get("decision") == gold_row.decision
    else:
        decision_correct = None

    gold_missing = set(normalize_evidence(gold_row.missing_information))
    pred_missing = set(normalize_evidence(pred_row.get("missing_information"))) if valid_row else set()
    missing_information_correct = valid_row and pred_missing == gold_missing

    evidence_metrics = _row_evidence_metrics(gold_row, pred_row, valid_row)

    row = {
        "key": {"case_id": gold_row.case_id, "variant_id": gold_row.variant_id, "question_id": gold_row.question_id},
        "case_id": gold_row.case_id,
        "variant_id": gold_row.variant_id,
        "question_id": gold_row.question_id,
        "skill": str((gold_row.model_extra or {}).get("skill", "unknown")),
        "answer_type": answer_type,
        "decision_required": bool(gold_row.decision_required),
        "status": pred_row.get("status"),
        "valid_row": valid_row,
        "answer_correct": answer_correct,
        "decision_correct": decision_correct,
        "missing_information_correct": missing_information_correct,
        "evidence_precision": evidence_metrics["precision"],
        "evidence_recall": evidence_metrics["recall"],
        "evidence_f1": evidence_metrics["f1"],
        "unsupported_evidence_rate": evidence_metrics["unsupported_rate"],
        "answer_error": None,
    }
    if strict and not valid_row:
        row["answer_correct"] = False
        row["decision_correct"] = False if gold_row.decision_required else None
        row["missing_information_correct"] = False
        row["evidence_precision"] = 0.0
        row["evidence_recall"] = 0.0
        row["evidence_f1"] = 0.0
        row["unsupported_evidence_rate"] = 0.0
    if valid_row and pred_answer is None:
        row["answer_error"] = "canonical answer missing or invalid"
    return row


def _aggregate_records(records: list[dict[str, Any]], *, strict: bool) -> dict[str, Any]:
    total_rows = len(records)
    answer_correct = sum(1 for row in records if row["answer_correct"])
    valid_rows = [row for row in records if row["valid_row"]]
    valid_count = len(valid_rows)
    decision_rows = [row for row in records if row["decision_required"]]
    valid_decision_rows = [row for row in valid_rows if row["decision_required"]]
    missing_correct = sum(1 for row in records if row["missing_information_correct"])
    evidence_precision = sum(row["evidence_precision"] for row in records)
    evidence_recall = sum(row["evidence_recall"] for row in records)
    evidence_f1 = sum(row["evidence_f1"] for row in records)
    unsupported_evidence_rate = sum(row["unsupported_evidence_rate"] for row in records)
    denominator = total_rows if strict else valid_count
    decision_denominator = len(decision_rows) if strict else len(valid_decision_rows)
    decision_numerator = sum(1 for row in (decision_rows if strict else valid_decision_rows) if row["decision_correct"])
    return {
        "count": total_rows,
        "valid_count": valid_count,
        "format_failures": total_rows - valid_count,
        "answer_accuracy": {
            "numerator": answer_correct,
            "denominator": denominator,
            "excluded_rows": total_rows - denominator,
            "failure_treatment": "format/runtime failures counted wrong" if strict else "format/runtime failures excluded from denominator",
            "value": _safe_div(answer_correct, denominator),
        },
        "decision_accuracy": {
            "numerator": decision_numerator,
            "denominator": decision_denominator,
            "excluded_rows": total_rows - decision_denominator,
            "failure_treatment": "format/runtime failures counted wrong" if strict else "format/runtime failures excluded from denominator",
            "value": _safe_div(decision_numerator, decision_denominator),
        },
        "missing_information_accuracy": {
            "numerator": missing_correct,
            "denominator": denominator,
            "excluded_rows": total_rows - denominator,
            "failure_treatment": "format/runtime failures counted wrong" if strict else "format/runtime failures excluded from denominator",
            "value": _safe_div(missing_correct, denominator),
        },
        "evidence_precision": {
            "numerator": evidence_precision,
            "denominator": denominator,
            "excluded_rows": total_rows - denominator,
            "failure_treatment": "format/runtime failures counted wrong" if strict else "format/runtime failures excluded from denominator",
            "value": _safe_div(evidence_precision, denominator),
        },
        "evidence_recall": {
            "numerator": evidence_recall,
            "denominator": denominator,
            "excluded_rows": total_rows - denominator,
            "failure_treatment": "format/runtime failures counted wrong" if strict else "format/runtime failures excluded from denominator",
            "value": _safe_div(evidence_recall, denominator),
        },
        "evidence_f1": {
            "numerator": evidence_f1,
            "denominator": denominator,
            "excluded_rows": total_rows - denominator,
            "failure_treatment": "format/runtime failures counted wrong" if strict else "format/runtime failures excluded from denominator",
            "value": _safe_div(evidence_f1, denominator),
        },
        "unsupported_evidence_rate": {
            "numerator": unsupported_evidence_rate,
            "denominator": denominator,
            "excluded_rows": total_rows - denominator,
            "failure_treatment": "format/runtime failures counted wrong" if strict else "format/runtime failures excluded from denominator",
            "value": _safe_div(unsupported_evidence_rate, denominator),
        },
        "decision_required_count": decision_denominator,
    }


def _group_records(records: list[dict[str, Any]], field_name: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record[field_name])].append(record)
    result: list[dict[str, Any]] = []
    for group_key, items in sorted(grouped.items()):
        aggregates = _aggregate_records(items, strict=False)
        result.append(
            {
                field_name: group_key,
                "count": aggregates["count"],
                "valid_count": aggregates["valid_count"],
                "format_failures": aggregates["format_failures"],
                "answer_accuracy": aggregates["answer_accuracy"]["value"],
                "strict_answer_accuracy": _aggregate_records(items, strict=True)["answer_accuracy"]["value"],
                "decision_accuracy": aggregates["decision_accuracy"]["value"],
                "strict_decision_accuracy": _aggregate_records(items, strict=True)["decision_accuracy"]["value"],
                "decision_required_count": aggregates["decision_required_count"],
                "evidence_precision": aggregates["evidence_precision"]["value"],
                "evidence_recall": aggregates["evidence_recall"]["value"],
                "evidence_f1": aggregates["evidence_f1"]["value"],
                "missing_information_accuracy": aggregates["missing_information_accuracy"]["value"],
                "strict_missing_information_accuracy": _aggregate_records(items, strict=True)["missing_information_accuracy"]["value"],
                "unsupported_evidence_rate": aggregates["unsupported_evidence_rate"]["value"],
                "strict_unsupported_evidence_rate": _aggregate_records(items, strict=True)["unsupported_evidence_rate"]["value"],
            }
        )
    return result


def _case_metrics(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["case_id"]].append(record)
    rows: list[dict[str, Any]] = []
    for case_id, items in sorted(grouped.items()):
        valid_count = sum(1 for row in items if row["valid_row"])
        format_failures = len(items) - valid_count
        valid_answer_accuracy = _safe_div(sum(1 for row in items if row["answer_correct"] and row["valid_row"]), valid_count)
        strict_answer_accuracy = _safe_div(sum(1 for row in items if row["answer_correct"]), len(items))
        valid_decision_rows = [row for row in items if row["valid_row"] and row["decision_required"]]
        strict_decision_rows = [row for row in items if row["decision_required"]]
        valid_decision_accuracy = _safe_div(sum(1 for row in valid_decision_rows if row["decision_correct"]), len(valid_decision_rows))
        strict_decision_accuracy = _safe_div(sum(1 for row in strict_decision_rows if row["decision_correct"]), len(strict_decision_rows))
        rows.append(
            {
                "case_id": case_id,
                "reasoning_mechanism": items[0]["skill"],
                "total_prompt_rows": len(items),
                "valid_rows": valid_count,
                "format_failures": format_failures,
                "valid_output_accuracy": valid_answer_accuracy,
                "strict_accuracy": strict_answer_accuracy,
                "valid_output_decision_accuracy": valid_decision_accuracy,
                "strict_decision_accuracy": strict_decision_accuracy,
            }
        )
    return rows


def _boolean_audit(records: list[dict[str, Any]], gold_by_key: dict[tuple[str, str, str], Any], terminal_by_key: dict[tuple[str, str, str], dict[str, Any]]) -> dict[str, Any]:
    boolean_records: list[dict[str, Any]] = []
    confusion = Counter()
    raw_distribution = Counter()
    gold_distribution = Counter()
    predicted_distribution = Counter()
    parseable_predicted = Counter()
    missing_predictions = 0

    for record in records:
        if record["answer_type"] != "boolean" or not record["valid_row"]:
            continue
        key = (record["case_id"], record["variant_id"], record["question_id"])
        gold_row = gold_by_key[key]
        pred_row = terminal_by_key[key]
        gold_answer = normalize_answer_value("boolean", gold_row.answer_normalized)
        pred_answer = _safe_normalize_answer("boolean", pred_row.get("answer")) if pred_row.get("status") == "ok" else None
        gold_distribution[gold_answer] += 1
        if pred_answer is None:
            missing_predictions += 1
            predicted_distribution["missing"] += 1
        else:
            predicted_distribution[pred_answer] += 1
            parseable_predicted[pred_answer] += 1
            confusion[(gold_answer, pred_answer)] += 1
        raw_answer = None
        raw_response = pred_row.get("raw_response")
        if isinstance(raw_response, dict):
            response = raw_response.get("response")
            if isinstance(response, dict):
                message = response.get("message")
                if isinstance(message, dict):
                    raw_answer = message.get("content")
        if isinstance(raw_answer, str):
            if '"answer": true' in raw_answer:
                raw_distribution["json_true"] += 1
            elif '"answer": false' in raw_answer:
                raw_distribution["json_false"] += 1
            elif '"answer": "True"' in raw_answer or "'True'" in raw_answer:
                raw_distribution["string_true"] += 1
            elif '"answer": "False"' in raw_answer or "'False'" in raw_answer:
                raw_distribution["string_false"] += 1
            elif '"answer"' not in raw_answer:
                raw_distribution["missing"] += 1
            else:
                raw_distribution["other"] += 1
        boolean_records.append(
            {
                "case_id": record["case_id"],
                "variant_id": record["variant_id"],
                "question_id": record["question_id"],
                "question": str((gold_row.model_extra or {}).get("question", "")),
                "gold_answer": gold_answer,
                "gold_decision": gold_row.decision,
                "raw_schema": (pred_row.get("raw_response") or {}).get("request", {}).get("format"),
                "raw_response": raw_answer,
                "parsed_canonical_answer": pred_answer,
                "exact_comparison": pred_answer == gold_answer,
                "predicted_json_boolean": pred_answer if pred_answer in {"true", "false"} else None,
                "predicted_missing": pred_answer is None,
            }
        )

    gold_true = gold_distribution["true"]
    gold_false = gold_distribution["false"]
    pred_true = predicted_distribution["true"]
    pred_false = predicted_distribution["false"]
    pred_missing = predicted_distribution["missing"]
    confusion_matrix = {
        "true": {"true": confusion[("true", "true")], "false": confusion[("true", "false")], "missing": gold_true - confusion[("true", "true")] - confusion[("true", "false")]},
        "false": {"true": confusion[("false", "true")], "false": confusion[("false", "false")], "missing": gold_false - confusion[("false", "true")] - confusion[("false", "false")]},
    }
    accuracy_true = _safe_div(confusion[("true", "true")], gold_true)
    accuracy_false = _safe_div(confusion[("false", "false")], gold_false)
    return {
        "count": len(boolean_records),
        "gold_distribution": {"true": gold_true, "false": gold_false},
        "predicted_distribution": {"true": pred_true, "false": pred_false, "missing": pred_missing},
        "raw_answer_distribution": dict(raw_distribution),
        "confusion_matrix": confusion_matrix,
        "accuracy_by_class": {"true": accuracy_true, "false": accuracy_false},
        "representative_errors": [row for row in boolean_records if not row["exact_comparison"]][:20],
    }


def _classify_format_failure(error_message: str, answer_type: str) -> str:
    message = error_message.lower()
    if "validation error for modelprediction" in message and "decision" in message and "input should be a valid string" in message:
        return "wrong_json_type_decision"
    if "validation error for modelprediction" in message and "answer" in message and "input should be a valid string" in message:
        return "wrong_json_type_answer"
    if "invalid threshold value" in message:
        return "noncanonical_free_text_threshold"
    if "invalid integer value" in message:
        return "noncanonical_free_text_integer"
    if "invalid datetime value" in message:
        return "noncanonical_free_text_datetime"
    if "invalid date value" in message:
        return "noncanonical_free_text_date"
    if "invalid date_range value" in message or "invalid date range value" in message:
        return "noncanonical_free_text_date_range"
    if "invalid boolean value" in message:
        return "noncanonical_free_text_boolean"
    if "invalid categorical value" in message:
        return "noncanonical_free_text_categorical"
    if "invalid code_set value" in message or "invalid code set value" in message:
        return "noncanonical_free_text_code_set"
    if "invalid money value" in message:
        return "noncanonical_free_text_money"
    if "json" in message and ("decode" in message or "parse" in message or "malformed" in message):
        return "malformed_json"
    if "validation error" in message:
        return f"schema_validation_error_{answer_type}"
    return f"other_{answer_type}"


def _format_failure_audit(terminal: TerminalPredictionJournal, gold_by_key: dict[tuple[str, str, str], Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for key, pred_row in terminal.by_key.items():
        if pred_row.get("status") == "ok":
            continue
        gold_row = gold_by_key[key]
        category = _classify_format_failure(str(pred_row.get("error") or ""), gold_row.answer_type)
        counts[category] += 1
        rows.append(
            {
                "case_id": gold_row.case_id,
                "variant_id": gold_row.variant_id,
                "question_id": gold_row.question_id,
                "answer_type": gold_row.answer_type,
                "error_category": category,
                "error_message": pred_row.get("error"),
                "raw_request_schema": None,
                "raw_response": pred_row.get("raw_response"),
                "terminal_status": pred_row.get("status"),
                "counted_as_wrong_in_strict": True,
            }
        )
    return {
        "count": len(rows),
        "category_counts": dict(sorted(counts.items())),
        "rows": rows,
    }


def _counterfactual_rows(gold_records: list[Any], terminal_by_key: dict[tuple[str, str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(dict)
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
        a_pred = _safe_normalize_answer(a.answer_type, terminal_by_key[a.key()].get("answer")) if terminal_by_key[a.key()].get("status") == "ok" else None
        b_pred = _safe_normalize_answer(b.answer_type, terminal_by_key[b.key()].get("answer")) if terminal_by_key[b.key()].get("status") == "ok" else None
        c_pred = _safe_normalize_answer(c.answer_type, terminal_by_key[c.key()].get("answer")) if terminal_by_key[c.key()].get("status") == "ok" else None

        ab_expected_change = a_gold != b_gold
        ac_expected_change = a_gold != c_gold

        ab_namespace = "ab_flip" if ab_expected_change else "ab_invariant"
        ab_left_valid = a_pred is not None
        ab_right_valid = b_pred is not None
        ab_valid_pair = ab_left_valid and ab_right_valid
        ab_score = 1 if (ab_valid_pair and ((a_pred != b_pred) if ab_expected_change else (a_pred == b_pred))) else 0
        rows.append(
            {
                "case_id": case_id,
                "question_id": question_id,
                "namespace": ab_namespace,
                "expected_relation": "flip" if ab_expected_change else "invariant",
                "expected_change": ab_expected_change,
                "left_variant": "A",
                "right_variant": "B",
                "left_answer": a_pred,
                "right_answer": b_pred,
                "gold_left_answer": a_gold,
                "gold_right_answer": b_gold,
                "left_valid": ab_left_valid,
                "right_valid": ab_right_valid,
                "valid_pair": ab_valid_pair,
                "score": ab_score,
            }
        )

        if ab_expected_change and ac_expected_change:
            continue
        ac_namespace = "ac_nuisance_flip" if (not ab_expected_change and ac_expected_change) else "ac_causal_invariant"
        ac_left_valid = a_pred is not None
        ac_right_valid = c_pred is not None
        ac_valid_pair = ac_left_valid and ac_right_valid
        ac_score = 1 if (ac_valid_pair and ((a_pred != c_pred) if ac_expected_change else (a_pred == c_pred))) else 0
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
                "left_valid": ac_left_valid,
                "right_valid": ac_right_valid,
                "valid_pair": ac_valid_pair,
                "score": ac_score,
            }
        )
    return rows


def _counterfactual_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["namespace"])].append(row)

    summary: dict[str, Any] = {}
    for namespace, items in sorted(grouped.items()):
        expected_denominator = len(items)
        valid_items = [row for row in items if row["valid_pair"]]
        strict_numerator = sum(int(row["score"]) for row in items)
        valid_numerator = sum(int(row["score"]) for row in valid_items)
        strict_denominator = expected_denominator
        valid_denominator = len(valid_items)
        strict_score = _safe_div(strict_numerator, strict_denominator)
        valid_score = _safe_div(valid_numerator, valid_denominator)
        is_flip = namespace in {"ab_flip", "ac_nuisance_flip"}
        strict_error_count = strict_denominator - strict_numerator
        valid_error_count = valid_denominator - valid_numerator
        summary[namespace] = {
            "namespace": namespace,
            "expected_denominator": expected_denominator,
            "strict": {
                "numerator": strict_numerator,
                "denominator": strict_denominator,
                "score": strict_score,
                "missed_update_count": strict_error_count if is_flip else 0,
                "missed_update_rate": _safe_div(strict_error_count, strict_denominator) if is_flip else 0.0,
                "over_update_count": strict_error_count if not is_flip else 0,
                "over_update_rate": _safe_div(strict_error_count, strict_denominator) if not is_flip else 0.0,
            },
            "valid_pair": {
                "numerator": valid_numerator,
                "denominator": valid_denominator,
                "score": valid_score,
                "excluded_pairs": strict_denominator - valid_denominator,
                "missed_update_count": valid_error_count if is_flip else 0,
                "missed_update_rate": _safe_div(valid_error_count, valid_denominator) if is_flip else 0.0,
                "over_update_count": valid_error_count if not is_flip else 0,
                "over_update_rate": _safe_div(valid_error_count, valid_denominator) if not is_flip else 0.0,
            },
            "rows": items,
        }
    return summary


def _counterfactual_overview(summary: dict[str, Any]) -> dict[str, Any]:
    flip_namespaces = ["ab_flip", "ac_nuisance_flip"]
    invariant_namespaces = ["ab_invariant", "ac_causal_invariant"]
    strict_flip_denominator = sum(summary[name]["strict"]["denominator"] for name in flip_namespaces if name in summary)
    strict_flip_numerator = sum(summary[name]["strict"]["numerator"] for name in flip_namespaces if name in summary)
    strict_invariant_denominator = sum(summary[name]["strict"]["denominator"] for name in invariant_namespaces if name in summary)
    strict_invariant_numerator = sum(summary[name]["strict"]["numerator"] for name in invariant_namespaces if name in summary)
    valid_flip_denominator = sum(summary[name]["valid_pair"]["denominator"] for name in flip_namespaces if name in summary)
    valid_flip_numerator = sum(summary[name]["valid_pair"]["numerator"] for name in flip_namespaces if name in summary)
    valid_invariant_denominator = sum(summary[name]["valid_pair"]["denominator"] for name in invariant_namespaces if name in summary)
    valid_invariant_numerator = sum(summary[name]["valid_pair"]["numerator"] for name in invariant_namespaces if name in summary)
    return {
        "ab_flip_strict": summary.get("ab_flip", {}).get("strict", {}),
        "ab_invariant_strict": summary.get("ab_invariant", {}).get("strict", {}),
        "ac_nuisance_flip_strict": summary.get("ac_nuisance_flip", {}).get("strict", {}),
        "ac_causal_invariant_strict": summary.get("ac_causal_invariant", {}).get("strict", {}),
        "ab_flip_valid_pair": summary.get("ab_flip", {}).get("valid_pair", {}),
        "ab_invariant_valid_pair": summary.get("ab_invariant", {}).get("valid_pair", {}),
        "ac_nuisance_flip_valid_pair": summary.get("ac_nuisance_flip", {}).get("valid_pair", {}),
        "ac_causal_invariant_valid_pair": summary.get("ac_causal_invariant", {}).get("valid_pair", {}),
        "strict": {
            "flip_numerator": strict_flip_numerator,
            "flip_denominator": strict_flip_denominator,
            "flip_score": _safe_div(strict_flip_numerator, strict_flip_denominator),
            "invariant_numerator": strict_invariant_numerator,
            "invariant_denominator": strict_invariant_denominator,
            "invariance_score": _safe_div(strict_invariant_numerator, strict_invariant_denominator),
            "missed_update_numerator": strict_flip_denominator - strict_flip_numerator,
            "missed_update_denominator": strict_flip_denominator,
            "missed_update_rate": _safe_div(strict_flip_denominator - strict_flip_numerator, strict_flip_denominator),
            "over_update_numerator": strict_invariant_denominator - strict_invariant_numerator,
            "over_update_denominator": strict_invariant_denominator,
            "over_update_rate": _safe_div(strict_invariant_denominator - strict_invariant_numerator, strict_invariant_denominator),
        },
        "valid_pair": {
            "flip_numerator": valid_flip_numerator,
            "flip_denominator": valid_flip_denominator,
            "flip_score": _safe_div(valid_flip_numerator, valid_flip_denominator),
            "invariant_numerator": valid_invariant_numerator,
            "invariant_denominator": valid_invariant_denominator,
            "invariance_score": _safe_div(valid_invariant_numerator, valid_invariant_denominator),
            "missed_update_numerator": valid_flip_denominator - valid_flip_numerator,
            "missed_update_denominator": valid_flip_denominator,
            "missed_update_rate": _safe_div(valid_flip_denominator - valid_flip_numerator, valid_flip_denominator),
            "over_update_numerator": valid_invariant_denominator - valid_invariant_numerator,
            "over_update_denominator": valid_invariant_denominator,
            "over_update_rate": _safe_div(valid_invariant_denominator - valid_invariant_numerator, valid_invariant_denominator),
        },
    }


def build_full_audit(
    *,
    gold_path: str | Path,
    predictions_path: str | Path,
    prompts_path: str | Path,
) -> dict[str, Any]:
    gold = load_gold(gold_path)
    terminal = load_terminal_predictions(predictions_path)
    gold_by_key = gold.by_key

    missing = [key for key in gold_by_key if key not in terminal.by_key]
    extra = [key for key in terminal.by_key if key not in gold_by_key]
    if missing or extra:
        raise ValueError(f"key mismatch: missing={len(missing)} extra={len(extra)}")

    row_records = [_build_row_record(gold_by_key[key], terminal.by_key[key], strict=False) for key in gold_by_key]
    strict_row_records = [_build_row_record(gold_by_key[key], terminal.by_key[key], strict=True) for key in gold_by_key]
    valid_output = _aggregate_records(row_records, strict=False)
    strict_end_to_end = _aggregate_records(strict_row_records, strict=True)

    by_case = _case_metrics(row_records)
    by_answer_type = _group_records(row_records, "answer_type")
    by_skill = _group_records(row_records, "skill")
    boolean_audit = _boolean_audit(row_records, gold_by_key, terminal.by_key)
    format_failure_audit = _format_failure_audit(terminal, gold_by_key)
    counterfactual_rows = _counterfactual_rows(list(gold.records), terminal.by_key)
    counterfactual_summary = _counterfactual_summary(counterfactual_rows)
    counterfactual = {
        "rows": counterfactual_rows,
        "namespaces": counterfactual_summary,
        **counterfactual_summary,
        **_counterfactual_overview(counterfactual_summary),
    }

    prompt_rows = _load_jsonl(prompts_path)
    prompt_keys = {(row["case_id"], row["variant_id"], row["question_id"]) for row in prompt_rows}
    gold_keys = set(gold_by_key)
    prediction_keys = set(terminal.by_key)

    prompt_key_set = set(prompt_keys)
    return {
        "counts": {
            "case_directories": len({record.case_id for record in gold.records}),
            "unique_case_ids": len({record.case_id for record in gold.records}),
            "variants": len({record.variant_id for record in gold.records}),
            "prompt_rows": len(prompt_rows),
            "gold_rows": len(gold.records),
            "prediction_rows": terminal.total_rows,
            "unique_prediction_keys": len(terminal.by_key),
            "valid_rows": valid_output["valid_count"],
            "format_failures": valid_output["format_failures"],
            "duplicate_appended_rows": terminal.total_rows - len(terminal.by_key),
            "attempts_over_one": sum(1 for count in terminal.attempts_by_key.values() if count > 1),
        },
        "key_alignment": {
            "prompt_keys": len(prompt_keys),
            "gold_keys": len(gold_keys),
            "prediction_keys": len(prediction_keys),
            "report_keys": len(row_records),
            "no_missing_gold": not (gold_keys - prediction_keys),
            "no_orphan_predictions": not (prediction_keys - gold_keys),
            "no_missing_prompts": not (prompt_key_set - gold_keys),
            "no_orphan_prompts": not (gold_keys - prompt_key_set),
            "no_duplicates": len(prediction_keys) == len(row_records),
        },
        "layers": {
            "valid_output": valid_output,
            "strict_end_to_end": strict_end_to_end,
        },
        "by_case_id": by_case,
        "by_answer_type": by_answer_type,
        "by_reasoning_mechanism": by_skill,
        "boolean_confusion_audit": boolean_audit,
        "format_failure_audit": format_failure_audit,
        "counterfactual": counterfactual,
        "gold_path": str(gold_path),
        "predictions_path": str(predictions_path),
        "prompts_path": str(prompts_path),
        "gold_keys": sorted(map(list, gold_keys)),
        "prediction_keys": sorted(map(list, prediction_keys)),
        "prompt_keys": sorted(map(list, prompt_keys)),
    }


def _csv_rows_for_case(case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return case_rows


def write_full_audit(audit: dict[str, Any], output_dir: str | Path, *, prefix: str) -> dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_report = output_dir / f"{prefix}_report.json"

    report_json = output_dir / f"{prefix}_report_corrected.json"
    report_csv = output_dir / f"{prefix}_report_corrected.csv"
    counterfactual_json = output_dir / f"{prefix}_counterfactual_corrected.json"
    boolean_json = output_dir / f"{prefix}_boolean_confusion_audit.json"
    format_failure_json = output_dir / f"{prefix}_format_failure_audit.json"
    manifest_json = output_dir / f"{prefix}_audit_manifest.json"

    report_payload = {
        "counts": audit["counts"],
        "key_alignment": audit["key_alignment"],
        "layers": audit["layers"],
        "by_case_id": audit["by_case_id"],
        "by_answer_type": audit["by_answer_type"],
        "by_reasoning_mechanism": audit["by_reasoning_mechanism"],
    }
    report_json.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    counterfactual_json.write_text(json.dumps(audit["counterfactual"], ensure_ascii=False, indent=2), encoding="utf-8")
    boolean_json.write_text(json.dumps(audit["boolean_confusion_audit"], ensure_ascii=False, indent=2), encoding="utf-8")
    format_failure_json.write_text(json.dumps(audit["format_failure_audit"], ensure_ascii=False, indent=2), encoding="utf-8")

    with report_csv.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "case_id",
            "reasoning_mechanism",
            "total_prompt_rows",
            "valid_rows",
            "format_failures",
            "valid_output_accuracy",
            "strict_accuracy",
            "valid_output_decision_accuracy",
            "strict_decision_accuracy",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in audit["by_case_id"]:
            writer.writerow({field: row.get(field, "") for field in fieldnames})

    manifest = {
        "report_json": str(report_json),
        "report_csv": str(report_csv),
        "counterfactual_json": str(counterfactual_json),
        "boolean_confusion_audit": str(boolean_json),
        "format_failure_audit": str(format_failure_json),
        "source_hashes": {
            "gold": _sha256(Path(audit["gold_path"])),
            "predictions": _sha256(Path(audit["predictions_path"])),
            "prompts": _sha256(Path(audit["prompts_path"])),
        },
        "previous_hashes": {
            "report_json": _sha256(previous_report) if previous_report.exists() else None,
        },
        "hashes": {
            "report_json": _sha256(report_json),
            "report_csv": _sha256(report_csv),
            "counterfactual_json": _sha256(counterfactual_json),
            "boolean_confusion_audit": _sha256(boolean_json),
            "format_failure_audit": _sha256(format_failure_json),
        },
    }
    manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**manifest, "manifest_json": str(manifest_json), "manifest_hash": _sha256(manifest_json)}


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
