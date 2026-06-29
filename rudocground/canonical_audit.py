from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .models import coerce_output_answer, normalize_answer_value
from .providers.codex_cli_provider import _codex_schema


NUMERICISH_ANSWER_TYPES = {"money", "integer", "threshold", "date", "date_range", "datetime"}


@dataclass(frozen=True)
class AuditArtifacts:
    records: list[dict[str, Any]]
    summary: dict[str, Any]


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _rows_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {(row["case_id"], row["variant_id"], row["question_id"]): row for row in rows}


def _raw_answer_value(pred: dict[str, Any]) -> Any:
    raw_response = pred.get("raw_response")
    if isinstance(raw_response, dict):
        response = raw_response.get("response")
        if isinstance(response, dict) and "answer" in response:
            return response.get("answer")
    return pred.get("answer")


def _classify_answer_error(gold_row: dict[str, Any], pred_row: dict[str, Any]) -> tuple[str, str]:
    answer_type = str(gold_row["answer_type"])
    gold_answer = gold_row["answer_normalized"]
    raw_answer = _raw_answer_value(pred_row)
    normalized_answer = pred_row.get("answer")

    if raw_answer is None or normalized_answer is None:
        return "other", "model returned no canonical answer payload"

    if answer_type in {"status", "categorical"}:
        raw_text = str(raw_answer).strip()
        gold_text = normalize_answer_value(answer_type, gold_answer)
        if raw_text.rstrip(".,;:!?") == gold_text:
            return (
                "noncanonical_categorical_label",
                "raw status string differs only by surface punctuation from the gold canonical label",
            )
        return (
            "noncanonical_categorical_label",
            "raw status string expresses the same categorical slot without using the canonical benchmark label",
        )

    if answer_type == "code_set":
        return (
            "noncanonical_code_set",
            "code-set answer did not use the canonical provider contract",
        )

    if answer_type in NUMERICISH_ANSWER_TYPES:
        try:
            canonical_from_raw = coerce_output_answer(answer_type, raw_answer)
        except Exception:
            canonical_from_raw = None
        gold_canonical = normalize_answer_value(answer_type, gold_answer)
        if canonical_from_raw is not None:
            try:
                canonical_from_raw_text = normalize_answer_value(answer_type, canonical_from_raw)
            except Exception:
                canonical_from_raw_text = None
        else:
            canonical_from_raw_text = None
        if canonical_from_raw_text is not None and canonical_from_raw_text == gold_canonical:
            return (
                "numeric_or_date_normalization",
                "raw answer contained the correct numeric/date value but normalization produced a different canonical value",
            )
        return (
            "wrong_reasoning",
            "raw answer resolved to a different numeric/date value than the gold canonical value",
        )

    if answer_type == "boolean":
        return (
            "other",
            "boolean answer was not emitted in canonical structured form",
        )

    return "other", "unclassified answer-format mismatch"


def build_canonical_format_audit(
    *,
    gold_path: str | Path = "data/gold.jsonl",
    predictions_path: str | Path = "results/gpt-5.4_all_cases.jsonl",
    prompts_path: str | Path = "prompts/all_cases_gpt-5.4.jsonl",
) -> AuditArtifacts:
    gold_rows = _load_jsonl(gold_path)
    predictions = _rows_by_key(_load_jsonl(predictions_path))
    prompts = _rows_by_key(_load_jsonl(prompts_path))

    records: list[dict[str, Any]] = []
    category_counts: dict[str, int] = defaultdict(int)
    for gold_row in gold_rows:
        key = (gold_row["case_id"], gold_row["variant_id"], gold_row["question_id"])
        pred_row = predictions.get(key)
        prompt_row = prompts.get(key)
        if pred_row is None or prompt_row is None:
            continue
        if pred_row.get("status") != "ok" or pred_row.get("answer") is None:
            error_category = "other"
            relation = "prediction did not produce a canonical answer payload"
        elif pred_row.get("answer") is not None:
            try:
                pred_canonical = normalize_answer_value(gold_row["answer_type"], pred_row.get("answer"))
            except Exception:
                pred_canonical = None
            gold_canonical = normalize_answer_value(gold_row["answer_type"], gold_row["answer_normalized"])
            if pred_canonical == gold_canonical:
                continue
            if gold_row["answer_type"] in {"status", "categorical"}:
                error_category, relation = _classify_answer_error(gold_row, pred_row)
            else:
                error_category, relation = _classify_answer_error(gold_row, pred_row)
        else:
            error_category = "other"
            relation = "prediction did not produce a canonical answer payload"

        if error_category == "other" and gold_row["answer_type"] == "boolean" and pred_row.get("answer") is None:
            relation = "model emitted null for a boolean answer"

        record = {
            "case_id": gold_row["case_id"],
            "variant_id": gold_row["variant_id"],
            "question_id": gold_row["question_id"],
            "question": gold_row["question"],
            "answer_type": gold_row["answer_type"],
            "gold_answer": gold_row["answer_normalized"],
            "raw_model_answer": _raw_answer_value(pred_row),
            "normalized_model_answer": pred_row.get("answer"),
            "current_output_schema": prompt_row["response_schema"],
            "semantic_relation_to_gold": relation,
            "error_category": error_category,
        }
        records.append(record)
        category_counts[error_category] += 1

    summary = {
        "total_errors": len(records),
        "category_counts": dict(sorted(category_counts.items())),
        "changed_schema_tasks": [],
    }
    for row in _load_jsonl(prompts_path):
        gold_row = next(
            (
                gold
                for gold in gold_rows
                if gold["case_id"] == row["case_id"]
                and gold["variant_id"] == row["variant_id"]
                and gold["question_id"] == row["question_id"]
            ),
            None,
        )
        if gold_row is None:
            continue
        response_schema = row["response_schema"]
        if (
            response_schema.get("answer_type") != gold_row.get("answer_type")
            or response_schema.get("allowed_answer_values")
            or response_schema.get("allowed_code_values")
        ):
            summary["changed_schema_tasks"].append(
                {
                    "case_id": row["case_id"],
                    "variant_id": row["variant_id"],
                    "question_id": row["question_id"],
                    "gold_answer_type": gold_row.get("answer_type"),
                    "answer_type": response_schema.get("answer_type"),
                }
            )
    return AuditArtifacts(records=records, summary=summary)


def _schema_answer_shape(schema: dict[str, Any]) -> dict[str, Any]:
    return schema["properties"]["answer"]


def build_schema_audit(
    *,
    gold_path: str | Path = "data/gold.jsonl",
    prompts_path: str | Path = "prompts/all_cases_gpt-5.4.jsonl",
) -> dict[str, Any]:
    gold_rows = _load_jsonl(gold_path)
    prompt_rows = _load_jsonl(prompts_path)
    gold_by_key = _rows_by_key(gold_rows)
    prompt_by_key = _rows_by_key(prompt_rows)

    errors: list[dict[str, Any]] = []
    errors_by_case: dict[str, int] = defaultdict(int)
    errors_by_question: dict[str, int] = defaultdict(int)
    decision_enum_schemas = 0
    code_set_enum_schemas = 0
    answer_enum_schemas = 0
    possible_label_leaks = 0
    allowed_answers_by_question: dict[tuple[str, str], list[str]] = {}

    for key, prompt_row in prompt_by_key.items():
        gold_row = gold_by_key.get(key)
        if gold_row is None:
            errors.append({"key": key, "error": "missing gold row"})
            continue

        schema = _codex_schema(_to_prompt_task(prompt_row))
        answer_schema = _schema_answer_shape(schema)
        answer_type = prompt_row.get("answer_type")

        if prompt_row["case_id"] != gold_row["case_id"] or prompt_row["variant_id"] != gold_row["variant_id"] or prompt_row["question_id"] != gold_row["question_id"]:
            errors.append({"key": key, "error": "prompt/gold key mismatch"})
            errors_by_case[prompt_row["case_id"]] += 1
            errors_by_question[prompt_row["question_id"]] += 1
            continue

        if prompt_row.get("decision_required"):
            decision_schema = schema["properties"]["decision"]
            if decision_schema.get("enum"):
                decision_enum_schemas += 1
            else:
                errors.append({"key": key, "error": "missing decision enum"})
                errors_by_case[prompt_row["case_id"]] += 1
                errors_by_question[prompt_row["question_id"]] += 1
                continue

        allowed_answers = prompt_row["response_schema"].get("allowed_answer_values")
        if answer_type in {"status", "categorical"} and allowed_answers:
            if not isinstance(answer_schema, dict) or answer_schema.get("type") != "string" or answer_schema.get("enum") != allowed_answers:
                errors.append({"key": key, "error": "status answer enum mismatch"})
                errors_by_case[prompt_row["case_id"]] += 1
                errors_by_question[prompt_row["question_id"]] += 1
                continue
            answer_enum_schemas += 1
            pair_key = (prompt_row["case_id"], prompt_row["question_id"])
            if pair_key in allowed_answers_by_question and allowed_answers_by_question[pair_key] != allowed_answers:
                errors.append({"key": key, "error": "A/B answer enum mismatch"})
                errors_by_case[prompt_row["case_id"]] += 1
                errors_by_question[prompt_row["question_id"]] += 1
                continue
            allowed_answers_by_question[pair_key] = allowed_answers
            gold_answer = normalize_answer_value("status", gold_row["answer_normalized"])
            if gold_answer not in allowed_answers:
                errors.append({"key": key, "error": "gold missing from answer enum"})
                errors_by_case[prompt_row["case_id"]] += 1
                errors_by_question[prompt_row["question_id"]] += 1
                continue
            if len(allowed_answers) < 2:
                errors.append({"key": key, "error": "singleton answer enum"})
                errors_by_case[prompt_row["case_id"]] += 1
                errors_by_question[prompt_row["question_id"]] += 1
                continue
        else:
            if answer_type in {"status", "categorical"} and allowed_answers not in (None, []):
                errors.append({"key": key, "error": "unexpected answer enum"})
                errors_by_case[prompt_row["case_id"]] += 1
                errors_by_question[prompt_row["question_id"]] += 1
                continue
            if answer_type in {"money", "integer", "threshold", "date", "date_range", "datetime", "boolean"} and answer_schema.get("enum"):
                errors.append({"key": key, "error": "numeric answer was turned into enum"})
                errors_by_case[prompt_row["case_id"]] += 1
                errors_by_question[prompt_row["question_id"]] += 1
                continue

        if answer_type == "code_set":
            if answer_schema.get("type") != "object":
                errors.append({"key": key, "error": "code_set answer schema must be object"})
                errors_by_case[prompt_row["case_id"]] += 1
                errors_by_question[prompt_row["question_id"]] += 1
                continue
            code_set_enum_schemas += 1
            if "uniqueItems" in json.dumps(answer_schema, ensure_ascii=False):
                errors.append({"key": key, "error": "code_set schema leaks cardinality"})
                errors_by_case[prompt_row["case_id"]] += 1
                errors_by_question[prompt_row["question_id"]] += 1
                continue

        if answer_type not in {"status", "categorical"} and answer_schema.get("enum"):
            errors.append({"key": key, "error": f"{answer_type} answer unexpectedly uses enum"})
            errors_by_case[prompt_row["case_id"]] += 1
            errors_by_question[prompt_row["question_id"]] += 1
            continue

    if not errors:
        possible_label_leaks = 0

    passed_tasks = len(prompt_rows) - len(errors)
    return {
        "total_tasks": len(prompt_rows),
        "passed_tasks": passed_tasks,
        "failed_tasks": len(errors),
        "errors_by_case_id": dict(sorted(errors_by_case.items())),
        "errors_by_question_id": dict(sorted(errors_by_question.items())),
        "decision_enum_schemas": decision_enum_schemas,
        "code_set_enum_schemas": code_set_enum_schemas,
        "answer_enum_schemas": answer_enum_schemas,
        "possible_label_leaks": possible_label_leaks,
        "errors": errors,
    }


def _to_prompt_task(prompt_row: dict[str, Any]):
    from .models import PromptTask

    return PromptTask.model_validate(prompt_row)
