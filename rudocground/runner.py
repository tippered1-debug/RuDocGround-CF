from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import csv
import json
import tempfile
import time
import uuid
from typing import Any

from .case_tools import CASE_PROMPT_COUNTS, CaseAuditError
from .io import DataFormatError, load_gold
from .metrics import evaluate_report
from .models import ModelPrediction, PredictionBody, PromptTask, coerce_output_answer, normalize_answer_value, normalize_evidence_doc_ids
from .providers import CodexCliProvider, GeminiProvider, MockProvider, ModelProvider, OllamaProvider, OpenAIProvider


POLICY_INSTRUCTIONS = {
    "answer_only": "Return only the answer fields and keep the JSON concise.",
    "structured": "Return a fully structured JSON object that follows the schema exactly.",
    "evidence_required": "Use the provided evidence and do not invent unsupported citations.",
}


@dataclass
class RunSummary:
    output_path: Path
    total_tasks: int
    selected_tasks: int
    successful: int
    failed: int
    skipped: int
    run_id: str


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise DataFormatError(f"{path}:{lineno}: {exc}") from exc
    return rows


def load_prompt_tasks(path: str | Path) -> list[PromptTask]:
    tasks: list[PromptTask] = []
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                task = PromptTask.model_validate_json(line)
            except Exception as exc:
                raise DataFormatError(f"{file_path}:{lineno}: {exc}") from exc
            tasks.append(task)
    return tasks


def _task_key(task: PromptTask) -> tuple[str, str, str]:
    return task.case_id, task.variant_id, task.question_id


def _validate_response_schema(task: PromptTask) -> None:
    if not isinstance(task.response_schema, dict):
        raise CaseAuditError(f"missing response_schema for {task.key()}")
    schema = task.response_schema
    required = {"case_id", "variant_id", "question_id", "answer", "decision", "evidence", "missing_information", "explanation"}
    missing = required - set(schema)
    if missing:
        raise CaseAuditError(f"invalid response_schema for {task.key()}: missing {sorted(missing)}")
    for field in ("case_id", "variant_id", "question_id"):
        if schema.get(field) != getattr(task, field):
            raise CaseAuditError(
                f"invalid response_schema for {task.key()}: {field}={schema.get(field)!r} does not match prompt task"
            )
    if bool(schema.get("decision_required", task.decision_required)) != task.decision_required:
        raise CaseAuditError(f"invalid response_schema for {task.key()}: decision_required mismatch")
    allowed_decisions = schema.get("allowed_decision_labels")
    if task.decision_required:
        if not isinstance(allowed_decisions, list) or len(allowed_decisions) < 2:
            raise CaseAuditError(f"invalid response_schema for {task.key()}: missing decision alternatives")
    allowed_answer_values = schema.get("allowed_answer_values")
    if task.answer_type in {"status", "categorical"}:
        if allowed_answer_values in (None, []):
            pass
        elif not isinstance(allowed_answer_values, list) or len(allowed_answer_values) < 2:
            raise CaseAuditError(f"invalid response_schema for {task.key()}: missing answer alternatives")
    elif allowed_answer_values not in (None, []):
        raise CaseAuditError(f"invalid response_schema for {task.key()}: answer alternatives not permitted")
    allowed_code_values = schema.get("allowed_code_values")
    if task.answer_type == "code_set" and (not isinstance(allowed_code_values, list) or not allowed_code_values):
        raise CaseAuditError(f"invalid response_schema for {task.key()}: missing code_set values")
    PredictionBody.model_validate(
        {
            "answer": schema["answer"],
            "decision": schema["decision"],
            "evidence": schema["evidence"],
            "missing_information": schema["missing_information"],
            "explanation": schema["explanation"],
        }
    )


def _validate_prompt_text(task: PromptTask, gold_rows: list[dict[str, Any]]) -> None:
    if task.prompt.count("[DOCUMENT doc_id=order_86_A]") + task.prompt.count("[DOCUMENT doc_id=order_86_B]") != 1 and "86-ОД" in task.prompt:
        raise CaseAuditError(f"prompt must contain exactly one order document section for {task.key()}")
    head, _, _ = task.prompt.partition("Context:")
    prompt_meta = head + json.dumps(task.response_schema, ensure_ascii=False)
    forbidden = ["answer_normalized", "required_evidence", "supporting_evidence", "must_change_from_other_variant"]
    for token in forbidden:
        if token in prompt_meta:
            raise CaseAuditError(f"prompt metadata leaks label token {token!r} for {task.key()}")
    for row in gold_rows:
        for evidence in row.get("required_evidence", []):
            if isinstance(evidence, str) and evidence in prompt_meta:
                raise CaseAuditError(f"prompt metadata leaks required evidence {evidence!r} for {task.key()}")

    gold_row = next(
        (
            row
            for row in gold_rows
            if row.get("case_id") == task.case_id
            and row.get("variant_id") == task.variant_id
            and row.get("question_id") == task.question_id
        ),
        None,
    )
    answer = None if gold_row is None else gold_row.get("answer_normalized")
    if isinstance(answer, (str, int, float, bool)):
        import re

        answer_text = str(answer)
        allowed_values = []
        schema = task.response_schema or {}
        for field in ("allowed_decision_labels", "allowed_answer_values", "allowed_code_values"):
            values = schema.get(field)
            if isinstance(values, list):
                allowed_values.extend(str(value) for value in values)
        if answer_text and not any(answer_text == value or answer_text in value for value in allowed_values):
            pattern = re.compile(rf"(?<!\\w){re.escape(answer_text)}(?!\\w)")
            if pattern.search(head):
                raise CaseAuditError(f"prompt metadata leaks gold answer for {task.key()}")


def _matching_gold_row(task: PromptTask, gold_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in gold_rows
            if row.get("case_id") == task.case_id
            and row.get("variant_id") == task.variant_id
            and row.get("question_id") == task.question_id
        ),
        None,
    )


def validate_prompt_bundle(tasks: list[PromptTask], gold_path: str | Path = "data/gold.jsonl") -> None:
    case_ids = {task.case_id for task in tasks}
    expected = sum(CASE_PROMPT_COUNTS.get(case_id, 0) for case_id in case_ids)
    if expected and len(tasks) != expected:
        raise CaseAuditError(f"expected {expected} prompt tasks, found {len(tasks)}")
    keys = [_task_key(task) for task in tasks]
    if len(keys) != len(set(keys)):
        raise CaseAuditError("duplicate prompt task keys found")
    gold_rows = _load_jsonl(Path(gold_path))
    allowed_answers_by_question: dict[tuple[str, str], list[str]] = {}
    for task in tasks:
        _validate_response_schema(task)
        gold_row = _matching_gold_row(task, gold_rows)
        if gold_row is None:
            raise CaseAuditError(f"missing gold row for {task.key()}")
        allowed_answers = (task.response_schema or {}).get("allowed_answer_values")
        if task.answer_type in {"status", "categorical"} and isinstance(allowed_answers, list) and allowed_answers:
            if len(allowed_answers) < 2:
                raise CaseAuditError(f"invalid response_schema for {task.key()}: missing answer alternatives")
            gold_answer = normalize_answer_value(task.answer_type, gold_row.get("answer_normalized"))
            if gold_answer not in allowed_answers:
                raise CaseAuditError(f"invalid response_schema for {task.key()}: gold answer missing from answer enum")
            question_key = (task.case_id, task.question_id)
            previous = allowed_answers_by_question.get(question_key)
            if previous is None:
                allowed_answers_by_question[question_key] = list(allowed_answers)
            elif previous != list(allowed_answers):
                raise CaseAuditError(f"invalid response_schema for {task.key()}: answer enum mismatch across variants")
        elif task.answer_type in {"status", "categorical"} and allowed_answers not in (None, []):
            raise CaseAuditError(f"invalid response_schema for {task.key()}: answer alternatives not permitted")
        _validate_prompt_text(task, gold_rows)


def _apply_policy(task: PromptTask, policy: str) -> PromptTask:
    policy = policy or "evidence_required"
    if policy == "evidence_required":
        return task
    prefix = POLICY_INSTRUCTIONS.get(policy)
    if prefix is None:
        raise CaseAuditError(f"unsupported policy: {policy}")
    return task.model_copy(
        update={
            "prompt": f"{prefix}\n\n{task.prompt}",
            "policy": policy,
        }
    )


def _prompt_doc_ids(task: PromptTask) -> list[str]:
    import re

    return re.findall(r"\[DOCUMENT doc_id=([^\]]+)\]", task.prompt)


def _normalize_prediction_payload(task: PromptTask, payload: dict[str, Any]) -> dict[str, Any]:
    doc_ids = _prompt_doc_ids(task)
    evidence = list(normalize_evidence_doc_ids(payload.get("evidence", [])))
    normalized_details: list[dict[str, Any]] = []
    raw_details = payload.get("evidence_details") or []
    if isinstance(raw_details, list):
        for item in raw_details:
            if isinstance(item, dict):
                doc_id = item.get("doc_id") or item.get("document_id")
                locator = item.get("locator")
                if doc_id is not None:
                    detail = {"doc_id": str(doc_id)}
                    if locator is not None:
                        detail["locator"] = locator
                    for key, value in item.items():
                        if key not in {"doc_id", "document_id", "locator"}:
                            detail[key] = value
                    normalized_details.append(detail)
            elif isinstance(item, str):
                normalized_details.append({"doc_id": item})
    for entry in normalized_details:
        if entry["doc_id"] in doc_ids and entry["doc_id"] not in evidence:
            evidence.append(entry["doc_id"])
    if not evidence and normalized_details:
        evidence = doc_ids[:1]
    answer = coerce_output_answer(task.answer_type, payload.get("answer"))
    return {
        "answer": answer,
        "decision": payload.get("decision", ""),
        "evidence": evidence,
        "evidence_details": normalized_details,
        "missing_information": payload.get("missing_information", []),
        "explanation": payload.get("explanation", ""),
    }


def _resolve_output_path(output_path: Path, policy: str) -> Path:
    if policy == "evidence_required":
        return output_path
    suffix = output_path.suffix or ".jsonl"
    stem = output_path.stem
    if stem.endswith(f"_{policy}"):
        return output_path
    return output_path.with_name(f"{stem}_{policy}{suffix}")


def _coerce_prediction(task: PromptTask, prediction: ModelPrediction | dict[str, Any], provider_name: str, model: str, run_id: str) -> ModelPrediction:
    if isinstance(prediction, ModelPrediction):
        payload = prediction.model_dump()
    else:
        payload = dict(prediction)
    payload = _normalize_prediction_payload(task, payload)
    payload.setdefault("case_id", task.case_id)
    payload.setdefault("variant_id", task.variant_id)
    payload.setdefault("question_id", task.question_id)
    payload.setdefault("model", model)
    payload.setdefault("provider", provider_name)
    payload.setdefault("run_id", run_id)
    payload.setdefault("status", "ok")
    payload.setdefault("error", None)
    return ModelPrediction.model_validate(payload)


def _error_prediction(task: PromptTask, provider_name: str, model: str, run_id: str, error: Exception) -> ModelPrediction:
    return ModelPrediction(
        case_id=task.case_id,
        variant_id=task.variant_id,
        question_id=task.question_id,
        answer=None,
        decision="error",
        evidence=[],
        missing_information=[],
        explanation="",
        model=model,
        provider=provider_name,
        run_id=run_id,
        latency_ms=0,
        input_tokens=0,
        output_tokens=0,
        status="error",
        error=str(error),
        raw_response=None,
    )


def _select_tasks(tasks: list[PromptTask], variant_id: str | None, question_id: str | None, limit: int | None) -> list[PromptTask]:
    selected = tasks
    if variant_id is not None:
        selected = [task for task in selected if task.variant_id == variant_id]
    if question_id is not None:
        selected = [task for task in selected if task.question_id == question_id]
    if limit is not None:
        selected = selected[:limit]
    return selected


def _load_existing_successes(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    successes: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _load_jsonl(path):
        key = (row.get("case_id"), row.get("variant_id"), row.get("question_id"))
        if row.get("status") == "ok":
            successes[key] = row
    return successes


def _build_provider(
    provider_name: str,
    model: str,
    codex_binary: str | None,
    max_retries: int,
    request_delay: float,
    min_request_interval: float,
    mock_provider: ModelProvider | None = None,
) -> ModelProvider:
    if mock_provider is not None:
        return mock_provider
    if provider_name == "openai":
        return OpenAIProvider(model=model, max_retries=max_retries, request_delay=request_delay)
    if provider_name == "gemini":
        return GeminiProvider(model=model, max_retries=max_retries, request_delay=request_delay, min_request_interval=min_request_interval)
    if provider_name == "codex":
        return CodexCliProvider(model=model, codex_binary=codex_binary)
    if provider_name == "ollama":
        return OllamaProvider(model=model)
    if provider_name == "mock":
        return MockProvider()
    raise CaseAuditError(f"unsupported provider: {provider_name}")


def run_model(
    prompts_path: str | Path,
    provider_name: str,
    model: str,
    output_path: str | Path,
    *,
    policy: str = "evidence_required",
    limit: int | None = None,
    question_id: str | None = None,
    variant_id: str | None = None,
    max_retries: int = 3,
    request_delay: float = 0.0,
    min_request_interval: float = 0.0,
    codex_binary: str | None = None,
    resume: bool = False,
    dry_run: bool = False,
    provider: ModelProvider | None = None,
) -> RunSummary:
    tasks = load_prompt_tasks(prompts_path)
    validate_prompt_bundle(tasks)

    selected = _select_tasks(tasks, variant_id, question_id, limit)
    resolved_output = _resolve_output_path(Path(output_path), policy)
    run_id = uuid.uuid4().hex

    if dry_run:
        return RunSummary(
            output_path=resolved_output,
            total_tasks=len(tasks),
            selected_tasks=len(selected),
            successful=0,
            failed=0,
            skipped=0,
            run_id=run_id,
        )

    active_provider = _build_provider(provider_name, model, codex_binary, max_retries, request_delay, min_request_interval, provider)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing_successes(resolved_output) if resume else {}

    final_rows: dict[tuple[str, str, str], dict[str, Any]] = dict(existing)
    successful = 0
    failed = 0
    skipped = 0

    for task in selected:
        key = task.key()
        if key in existing:
            skipped += 1
            continue
        effective_task = _apply_policy(task, policy)
        start = time.perf_counter()
        try:
            prediction = active_provider.generate(effective_task)
            if not isinstance(prediction, ModelPrediction):
                prediction = _coerce_prediction(effective_task, prediction, provider_name, model, run_id)
            else:
                payload = _normalize_prediction_payload(effective_task, prediction.model_dump())
                prediction = prediction.model_copy(
                    update={
                        "case_id": effective_task.case_id,
                        "variant_id": effective_task.variant_id,
                        "question_id": effective_task.question_id,
                        "answer": payload["answer"],
                        "decision": payload["decision"],
                        "evidence": payload["evidence"],
                        "evidence_details": payload["evidence_details"],
                        "missing_information": payload["missing_information"],
                        "explanation": payload["explanation"],
                        "model": model,
                        "provider": provider_name,
                        "run_id": run_id,
                    }
                )
            if prediction.status != "ok":
                raise ValueError(f"provider returned non-ok status: {prediction.status}")
            prediction.latency_ms = prediction.latency_ms or int((time.perf_counter() - start) * 1000)
            prediction.model = model
            prediction.provider = provider_name
            prediction.run_id = run_id
            final_rows[key] = prediction.model_dump(mode="json")
            successful += 1
            print(
                f"{task.question_id} {task.variant_id} ok latency={prediction.latency_ms}ms in={prediction.input_tokens} out={prediction.output_tokens}",
                file=__import__("sys").stderr,
            )
        except Exception as exc:
            failed += 1
            error_prediction = _error_prediction(effective_task, provider_name, model, run_id, exc)
            final_rows[key] = error_prediction.model_dump(mode="json")
            print(f"{task.question_id} {task.variant_id} error {exc}", file=__import__("sys").stderr)

    ordered_rows = [final_rows[task.key()] for task in selected if task.key() in final_rows]
    with resolved_output.open("w", encoding="utf-8") as handle:
        for row in ordered_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    return RunSummary(
        output_path=resolved_output,
        total_tasks=len(tasks),
        selected_tasks=len(selected),
        successful=successful,
        failed=failed,
        skipped=skipped,
        run_id=run_id,
    )


def _subset_file(rows: list[dict[str, Any]], predicate, *, mode: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".jsonl")
    path = Path(handle.name)
    with handle:
        for row in rows:
            if predicate(row):
                if mode == "gold":
                    output = dict(row)
                else:
                    output = {
                        "case_id": row["case_id"],
                        "variant_id": row["variant_id"],
                        "question_id": row["question_id"],
                        "answer": row["answer"],
                        "decision": row["decision"],
                        "evidence": row.get("evidence", []),
                        "missing_information": row.get("missing_information", []),
                        "explanation": row.get("explanation", ""),
                    }
                handle.write(json.dumps(output, ensure_ascii=False) + "\n")
    return path


def _read_successful_run_rows(path: str | Path) -> list[dict[str, Any]]:
    rows = _load_jsonl(Path(path))
    return [row for row in rows if row.get("status") == "ok"]


def _safe_normalize_answer(answer_type: str, value: Any) -> Any:
    if value is None:
        return ""
    try:
        return normalize_answer_value(answer_type, value)
    except ValueError:
        return value


def evaluate_run(gold_path: str | Path, predictions_path: str | Path, report_path: str | Path) -> dict[str, Any]:
    gold = load_gold(gold_path)
    run_rows = _read_successful_run_rows(predictions_path)
    if not run_rows:
        raise DataFormatError("no successful predictions found to evaluate")

    run_file = _subset_file(run_rows, lambda row: True, mode="pred")
    try:
        report = evaluate_report(str(gold_path), str(run_file))
    finally:
        run_file.unlink(missing_ok=True)

    gold_rows_by_key = {row.key(): row for row in gold.records}
    run_by_key = {(row["case_id"], row["variant_id"], row["question_id"]): row for row in run_rows}

    variant_reports: dict[str, dict[str, Any]] = {}
    for variant in ("A", "B"):
        variant_gold = _subset_file([row.model_dump(mode="json") for row in gold.records], lambda row, variant=variant: row["variant_id"] == variant, mode="gold")
        variant_preds = _subset_file(run_rows, lambda row, variant=variant: row["variant_id"] == variant, mode="pred")
        try:
            variant_report = evaluate_report(str(variant_gold), str(variant_preds))
        finally:
            variant_gold.unlink(missing_ok=True)
            variant_preds.unlink(missing_ok=True)
        variant_reports[variant] = variant_report.overall

    wrong_answers = []
    errors_by_skill: dict[str, list[str]] = defaultdict(list)
    for key, gold_record in gold_rows_by_key.items():
        pred = run_by_key.get(key)
        if pred is None:
            continue
        try:
            expected = normalize_answer_value(gold_record.answer_type, gold_record.answer_normalized)
            actual = normalize_answer_value(gold_record.answer_type, pred["answer"])
        except Exception:
            continue
        if expected != actual:
            skill = str((gold_record.model_extra or {}).get("skill", "unknown"))
            wrong_answers.append(
                {
                    "case_id": gold_record.case_id,
                    "variant_id": gold_record.variant_id,
                    "question_id": gold_record.question_id,
                    "skill": skill,
                    "expected": expected,
                    "actual": actual,
                }
            )
            errors_by_skill[skill].append(gold_record.question_id)

    q_interest = {}
    for qid in ("Q6", "Q7"):
        q_rows = [row for row in report.records if row["key"]["question_id"] == qid]
        q_interest[qid] = q_rows

    report_payload = {
        "overall": report.overall,
        "by_answer_type": report.by_answer_type,
        "counterfactual": report.counterfactual,
        "issues": report.issues,
        "records": report.records,
        "variant_metrics": variant_reports,
        "q6_q7": q_interest,
        "wrong_answers": wrong_answers,
        "errors_by_skill": dict(errors_by_skill),
    }

    report_target = Path(report_path)
    report_target.parent.mkdir(parents=True, exist_ok=True)
    report_target.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = report_target.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "variant_id",
                "question_id",
                "skill",
                "answer_type",
                "gold_answer",
                "pred_answer",
                "gold_decision",
                "pred_decision",
                "answer_correct",
                "decision_correct",
                "evidence_precision",
                "evidence_recall",
                "evidence_f1",
                "missing_information_correct",
                "unsupported_evidence_rate",
            ],
        )
        writer.writeheader()
        for record in report.records:
            key = record["key"]
            gold_record = gold_rows_by_key[(key["case_id"], key["variant_id"], key["question_id"])]
            pred = run_by_key[(key["case_id"], key["variant_id"], key["question_id"])]
            writer.writerow(
                {
                    "case_id": key["case_id"],
                    "variant_id": key["variant_id"],
                    "question_id": key["question_id"],
                    "skill": (gold_record.model_extra or {}).get("skill", ""),
                    "answer_type": gold_record.answer_type,
                    "gold_answer": _safe_normalize_answer(gold_record.answer_type, gold_record.answer_normalized),
                    "pred_answer": _safe_normalize_answer(gold_record.answer_type, pred["answer"]),
                    "gold_decision": gold_record.decision,
                    "pred_decision": pred["decision"],
                    "answer_correct": record["answer_correct"],
                    "decision_correct": record["decision_correct"],
                    "evidence_precision": record["evidence_precision"],
                    "evidence_recall": record["evidence_recall"],
                    "evidence_f1": record["evidence_f1"],
                    "missing_information_correct": record["missing_information_correct"],
                    "unsupported_evidence_rate": record["unsupported_evidence_rate"],
                }
            )

    return report_payload
