from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import math
import re
import time
from typing import Any

from .io import load_gold
from .models import PromptTask, coerce_output_answer
from .providers.ollama_provider import OllamaProvider
from .runner import load_prompt_tasks, evaluate_run


BATCH_SYSTEM_PROMPT = (
    "Ты проходишь закрытый тест RuDocGround-CF. "
    "Используй только документы из Context. "
    "Верни только JSON-объект без Markdown. "
    "Верхний уровень ответа должен содержать ключи всех вопросов из списка. "
    "Для каждого вопроса верни объект с полями answer, decision, evidence, evidence_details, missing_information, explanation. "
    "Для boolean верни JSON boolean. "
    "Для code_set верни массив canonical codes, а не pipe-joined string. "
    "Не используй семантическую нормализацию и не выдумывай документы."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _question_number(question_id: str) -> tuple[int, str]:
    match = re.fullmatch(r"Q(\d+)", question_id)
    if match:
        return int(match.group(1)), question_id
    return 10_000, question_id


def _split_context_from_prompt(prompt: str) -> str:
    marker = "Context:"
    if marker not in prompt:
        raise ValueError("prompt missing Context section")
    return prompt.split(marker, 1)[1].strip()


def _effective_answer_type(task: PromptTask) -> str:
    if task.answer_type:
        return task.answer_type
    schema = task.response_schema or {}
    answer_type = schema.get("answer_type")
    return str(answer_type) if answer_type is not None else "categorical"


def _allowed_answer_values(task: PromptTask) -> list[str]:
    schema = task.response_schema or {}
    values = schema.get("allowed_answer_values")
    if isinstance(values, list):
        return [str(item) for item in values if str(item).strip()]
    return []


def _allowed_code_values(task: PromptTask) -> list[str]:
    schema = task.response_schema or {}
    values = schema.get("allowed_code_values")
    if isinstance(values, list):
        return [str(item) for item in values if str(item).strip()]
    return []


def _allowed_decision_labels(task: PromptTask) -> list[str]:
    schema = task.response_schema or {}
    values = schema.get("allowed_decision_labels")
    if isinstance(values, list):
        return [str(item) for item in values if str(item).strip()]
    decision = schema.get("decision")
    if isinstance(decision, str) and decision.strip():
        return [decision.strip()]
    return []


def _answer_schema(task: PromptTask) -> dict[str, Any]:
    answer_type = _effective_answer_type(task)
    allowed_answers = _allowed_answer_values(task)
    if allowed_answers:
        return {"type": "string", "enum": allowed_answers}
    if answer_type == "boolean":
        return {"type": "boolean"}
    if answer_type == "integer":
        return {"type": "integer"}
    if answer_type == "money":
        return {"anyOf": [{"type": "number"}, {"type": "string"}]}
    if answer_type == "code_set":
        allowed_codes = _allowed_code_values(task)
        item_schema: dict[str, Any] = {"type": "string"}
        if allowed_codes:
            item_schema["enum"] = allowed_codes
        return {"type": "array", "items": item_schema, "uniqueItems": True}
    if answer_type == "json":
        return {
            "anyOf": [
                {"type": "object"},
                {"type": "array"},
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {"type": "null"},
            ]
        }
    if answer_type in {"date", "datetime", "date_range", "categorical", "identifier", "status", "threshold"}:
        return {"type": "string"}
    return {"type": "string"}


def _decision_schema(task: PromptTask) -> dict[str, Any]:
    if task.decision_required:
        labels = _allowed_decision_labels(task)
        if labels:
            return {"type": "string", "enum": labels}
        return {"type": "string"}
    return {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _question_schema(task: PromptTask) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "answer": _answer_schema(task),
            "decision": _decision_schema(task),
            "evidence": {"type": "array", "items": {"type": "string"}, "default": []},
            "evidence_details": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "doc_id": {"type": "string"},
                        "locator": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    },
                    "required": ["doc_id", "locator"],
                },
                "default": [],
            },
            "missing_information": {"type": "array", "items": {"type": "string"}, "default": []},
            "explanation": {"type": "string", "default": ""},
        },
        "required": ["answer", "decision", "evidence", "evidence_details", "missing_information", "explanation"],
    }


def _batch_schema(batch_tasks: list[PromptTask]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for task in batch_tasks:
        properties[task.question_id] = _question_schema(task)
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": [task.question_id for task in batch_tasks],
    }


def _build_batch_prompt(case_id: str, variant_id: str, context_text: str, batch_tasks: list[PromptTask], questions: dict[str, str]) -> str:
    lines = [
        f"Case ID: {case_id}",
        f"Variant ID: {variant_id}",
        "Context:",
        context_text,
        "",
        "Questions:",
    ]
    for task in batch_tasks:
        qtext = questions.get(task.question_id, "")
        meta = [
            f"answer_type={_effective_answer_type(task)}",
            f"decision_required={str(bool(task.decision_required)).lower()}",
        ]
        if task.decision_required:
            labels = _allowed_decision_labels(task)
            if labels:
                meta.append(f"allowed_decisions={json.dumps(labels, ensure_ascii=False)}")
        if _effective_answer_type(task) == "code_set":
            codes = _allowed_code_values(task)
            if codes:
                meta.append(f"allowed_codes={json.dumps(codes, ensure_ascii=False)}")
        allowed_answers = _allowed_answer_values(task)
        if allowed_answers:
            meta.append(f"allowed_answers={json.dumps(allowed_answers, ensure_ascii=False)}")
        lines.append(f"- {task.question_id} | {'; '.join(meta)}: {qtext}")
    lines.extend(
        [
            "",
            "Return an object with one top-level key per question id.",
            "For code_set answers, return JSON arrays of canonical codes.",
            "Do not add extra keys.",
        ]
    )
    return "\n".join(lines)


def _chunk_tasks(tasks: list[PromptTask], batch_size: int) -> list[list[PromptTask]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    return [tasks[i : i + batch_size] for i in range(0, len(tasks), batch_size)]


def _estimate_tokens(*parts: str) -> int:
    total_chars = sum(len(part) for part in parts)
    return max(1, math.ceil(total_chars / 4))


def _load_questions_from_gold(gold_path: Path) -> dict[tuple[str, str, str], str]:
    gold = load_gold(gold_path)
    return {row.key(): row.question for row in gold.records if hasattr(row, "question")}


def _load_gold_records(gold_path: Path) -> dict[tuple[str, str, str], Any]:
    gold = load_gold(gold_path)
    return {row.key(): row for row in gold.records}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        try:
            import os

            os.fsync(handle.fileno())
        except Exception:
            pass


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _existing_successes(path: Path) -> set[tuple[str, str, str]]:
    successes = set()
    for row in _load_jsonl(path):
        if row.get("status") == "ok":
            successes.add((row.get("case_id"), row.get("variant_id"), row.get("question_id")))
    return successes


def _build_batches(tasks: list[PromptTask], num_ctx: int, questions: dict[tuple[str, str, str], str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[PromptTask]] = {}
    for task in tasks:
        grouped.setdefault((task.case_id, task.variant_id), []).append(task)
    batches: list[dict[str, Any]] = []
    for (case_id, variant_id), variant_tasks in sorted(grouped.items()):
        variant_tasks = sorted(variant_tasks, key=lambda item: _question_number(item.question_id))
        first_context = _split_context_from_prompt(variant_tasks[0].prompt)
        prompt = _build_batch_prompt(case_id, variant_id, first_context, variant_tasks, {k[2]: v for k, v in questions.items() if k[0] == case_id and k[1] == variant_id})
        schema = _batch_schema(variant_tasks)
        estimate = _estimate_tokens(prompt, json.dumps(schema, ensure_ascii=False))
        if estimate > int(num_ctx * 0.85) and len(variant_tasks) > 7:
            for index, chunk in enumerate(_chunk_tasks(variant_tasks, 7), start=1):
                chunk_prompt = _build_batch_prompt(
                    case_id,
                    variant_id,
                    first_context,
                    chunk,
                    {k[2]: v for k, v in questions.items() if k[0] == case_id and k[1] == variant_id},
                )
                batches.append(
                    {
                        "case_id": case_id,
                        "variant_id": variant_id,
                        "batch_label": f"part{index}",
                        "batch_strategy": "split_7",
                        "question_ids": [task.question_id for task in chunk],
                        "tasks": chunk,
                        "prompt": chunk_prompt,
                        "schema": _batch_schema(chunk),
                        "estimated_tokens": _estimate_tokens(chunk_prompt, json.dumps(_batch_schema(chunk), ensure_ascii=False)),
                    }
                )
        else:
            batches.append(
                {
                    "case_id": case_id,
                    "variant_id": variant_id,
                    "batch_label": "full",
                    "batch_strategy": "variant_batched",
                    "question_ids": [task.question_id for task in variant_tasks],
                    "tasks": variant_tasks,
                    "prompt": prompt,
                    "schema": schema,
                    "estimated_tokens": estimate,
                }
            )
    return batches


def _batch_key(case_id: str, variant_id: str, batch_label: str) -> str:
    return f"{case_id}|{variant_id}|{batch_label}"


def _flatten_batch_response(
    *,
    batch: dict[str, Any],
    parsed: dict[str, Any],
    provider: OllamaProvider,
    request_body: dict[str, Any],
    response_body: dict[str, Any],
    latency_ms: int,
    prompt_eval_count: int | None,
    eval_count: int | None,
    batch_response_path: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    task_map = {task.question_id: task for task in batch["tasks"]}
    for task in batch["tasks"]:
        payload = parsed.get(task.question_id)
        if not isinstance(payload, dict):
            raise ValueError(f"missing structured payload for {task.question_id}")
        row = {
            "case_id": task.case_id,
            "variant_id": task.variant_id,
            "question_id": task.question_id,
            "answer": coerce_output_answer(_effective_answer_type(task), payload.get("answer")),
            "decision": payload.get("decision"),
            "evidence": payload.get("evidence", []),
            "evidence_details": payload.get("evidence_details", []),
            "missing_information": payload.get("missing_information", []),
            "explanation": payload.get("explanation", ""),
            "answer_type": _effective_answer_type(task),
            "decision_required": bool(task.decision_required),
            "model": provider.model,
            "provider": "ollama",
            "protocol": "variant_batched",
            "batch_case_id": batch["case_id"],
            "batch_variant_id": batch["variant_id"],
            "batch_label": batch["batch_label"],
            "batch_strategy": batch["batch_strategy"],
            "batch_question_ids": batch["question_ids"],
            "batch_response_path": batch_response_path,
            "latency_ms": latency_ms,
            "input_tokens": prompt_eval_count,
            "output_tokens": eval_count,
            "status": "ok",
            "error": None,
            "raw_response": {
                "request": request_body,
                "response": response_body,
                "parsed_response": parsed,
            },
        }
        rows.append(row)
    return rows


def run_variant_batched(
    *,
    prompts_path: str | Path,
    gold_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
    counterfactual_path: str | Path,
    manifest_path: str | Path,
    model: str = "qwen3:8b",
    base_url: str = "http://127.0.0.1:11434/api/chat",
    num_ctx: int = 16384,
    num_predict: int = 4096,
    temperature: float = 0.0,
    seed: int = 42,
    keep_alive: str = "30m",
    resume: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    prompts_path = Path(prompts_path)
    gold_path = Path(gold_path)
    output_path = Path(output_path)
    report_path = Path(report_path)
    counterfactual_path = Path(counterfactual_path)
    manifest_path = Path(manifest_path)
    batches_dir = output_path.parent / f"{output_path.stem}_batches"
    manifest_rows = load_prompt_tasks(prompts_path)
    question_texts = _load_questions_from_gold(gold_path)
    gold_records = _load_gold_records(gold_path)
    batches = _build_batches(manifest_rows, num_ctx, question_texts)

    provider = OllamaProvider(
        model=model,
        base_url=base_url,
        num_ctx=num_ctx,
        num_predict=num_predict,
        temperature=temperature,
        seed=seed,
        keep_alive=keep_alive,
        stream=False,
        think=False,
        max_retries=3,
    )

    if dry_run:
        return {
            "status": "dry_run",
            "batch_count": len(batches),
            "output_path": str(output_path),
            "report_path": str(report_path),
            "counterfactual_path": str(counterfactual_path),
            "manifest_path": str(manifest_path),
        }

    existing_successes = _existing_successes(output_path) if resume else set()
    completed_batches = 0
    failed_batches = 0
    total_attempts = 0
    all_row_keys: set[tuple[str, str, str]] = set(existing_successes)
    attempts_by_batch: dict[str, int] = {}
    batch_status: dict[str, Any] = {}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    batches_dir.mkdir(parents=True, exist_ok=True)

    if not resume:
        output_path.write_text("", encoding="utf-8")

    for batch in batches:
        batch_id = _batch_key(batch["case_id"], batch["variant_id"], batch["batch_label"])
        if all((batch["case_id"], batch["variant_id"], qid) in existing_successes for qid in batch["question_ids"]):
            batch_status[batch_id] = {
                "status": "completed",
                "attempts": 0,
                "completed_at": _utc_now(),
                "batch_strategy": batch["batch_strategy"],
                "question_ids": batch["question_ids"],
                "estimated_tokens": batch["estimated_tokens"],
                "skipped": True,
            }
            continue
        batch_attempts = 0
        last_exc: Exception | None = None
        batch_response_path = batches_dir / f"{batch_id.replace('|', '__')}.json"
        for attempt in range(1, 4):
            batch_attempts += 1
            total_attempts += 1
            started = time.perf_counter()
            try:
                result = provider._chat(
                    system_prompt=BATCH_SYSTEM_PROMPT,
                    user_prompt=batch["prompt"],
                    response_schema=batch["schema"],
                )
                latency_ms = int((time.perf_counter() - started) * 1000)
                parsed = result.parsed_payload
                if not isinstance(parsed, dict):
                    raise RuntimeError("batch response is not a JSON object")
                if set(parsed) != set(batch["question_ids"]):
                    missing = [qid for qid in batch["question_ids"] if qid not in parsed]
                    extra = [qid for qid in parsed if qid not in batch["question_ids"]]
                    raise RuntimeError(f"batch key mismatch missing={missing[:5]} extra={extra[:5]}")
                flattened = _flatten_batch_response(
                    batch=batch,
                    parsed=parsed,
                    provider=provider,
                    request_body=result.request_body,
                    response_body=result.response_body,
                    latency_ms=latency_ms,
                    prompt_eval_count=result.prompt_eval_count,
                    eval_count=result.eval_count,
                    batch_response_path=str(batch_response_path),
                )
                for row in flattened:
                    all_row_keys.add((row["case_id"], row["variant_id"], row["question_id"]))
                _append_jsonl(output_path, flattened)
                _write_json(
                    batch_response_path,
                    {
                        "batch_id": batch_id,
                        "case_id": batch["case_id"],
                        "variant_id": batch["variant_id"],
                        "batch_label": batch["batch_label"],
                        "batch_strategy": batch["batch_strategy"],
                        "question_ids": batch["question_ids"],
                        "request": result.request_body,
                        "response": result.response_body,
                        "parsed_response": parsed,
                        "latency_ms": latency_ms,
                        "prompt_eval_count": result.prompt_eval_count,
                        "eval_count": result.eval_count,
                    },
                )
                completed_batches += 1
                batch_status[batch_id] = {
                    "status": "completed",
                    "attempts": batch_attempts,
                    "completed_at": _utc_now(),
                    "batch_strategy": batch["batch_strategy"],
                    "question_ids": batch["question_ids"],
                    "estimated_tokens": batch["estimated_tokens"],
                    "response_path": str(batch_response_path),
                }
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 3:
                    time.sleep(min(2 ** (attempt - 1), 8))
                continue
        else:
            failed_batches += 1
            batch_status[batch_id] = {
                "status": "failed",
                "attempts": batch_attempts,
                "failed_at": _utc_now(),
                "batch_strategy": batch["batch_strategy"],
                "question_ids": batch["question_ids"],
                "estimated_tokens": batch["estimated_tokens"],
                "error": str(last_exc),
            }

        _write_json(
            manifest_path,
            {
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "protocol": "variant_batched",
                "model": model,
                "provider": "ollama",
                "base_url": base_url,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
                "temperature": temperature,
                "seed": seed,
                "keep_alive": keep_alive,
                "prompt_sha256": _sha256_file(prompts_path),
                "gold_sha256": _sha256_file(gold_path),
                "output_sha256": _sha256_file(output_path) if output_path.exists() else None,
                "report_sha256": _sha256_file(report_path) if report_path.exists() else None,
                "counterfactual_sha256": _sha256_file(counterfactual_path) if counterfactual_path.exists() else None,
                "batches": batch_status,
                "rows_written": len(all_row_keys),
                "completed_batches": completed_batches,
                "failed_batches": failed_batches,
                "total_batches": len(batches),
                "total_attempts": total_attempts,
            },
        )

    if output_path.exists():
        # Ensure ordering is stable and reportable.
        rows = _load_jsonl(output_path)
        ordered = sorted(rows, key=lambda row: (row["case_id"], row["variant_id"], row["question_id"]))
        output_path.write_text("", encoding="utf-8")
        _append_jsonl(output_path, ordered)

    report = evaluate_run(gold_path, output_path, report_path)
    counterfactual_path.write_text(json.dumps(report["counterfactual"], ensure_ascii=False, indent=2), encoding="utf-8")

    final_manifest = {
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "status": "complete" if len(all_row_keys) == len(manifest_rows) else "incomplete",
        "protocol": "variant_batched",
        "model": model,
        "provider": "ollama",
        "base_url": base_url,
        "num_ctx": num_ctx,
        "num_predict": num_predict,
        "temperature": temperature,
        "seed": seed,
        "keep_alive": keep_alive,
        "prompt_sha256": _sha256_file(prompts_path),
        "gold_sha256": _sha256_file(gold_path),
        "output_sha256": _sha256_file(output_path) if output_path.exists() else None,
        "report_sha256": _sha256_file(report_path) if report_path.exists() else None,
        "counterfactual_sha256": _sha256_file(counterfactual_path) if counterfactual_path.exists() else None,
        "rows_written": len(all_row_keys),
        "expected_rows": len(manifest_rows),
        "completed_batches": completed_batches,
        "failed_batches": failed_batches,
        "total_batches": len(batches),
        "total_attempts": total_attempts,
        "batches_dir": str(batches_dir),
        "output_path": str(output_path),
        "report_path": str(report_path),
        "counterfactual_path": str(counterfactual_path),
        "batches": batch_status,
        "hashes": {
            "prompts": _sha256_file(prompts_path),
            "gold": _sha256_file(gold_path),
            "output": _sha256_file(output_path),
            "report": _sha256_file(report_path),
            "counterfactual": _sha256_file(counterfactual_path),
        },
    }
    _write_json(manifest_path, final_manifest)
    return {
        "status": final_manifest["status"],
        "rows_written": len(all_row_keys),
        "expected_rows": len(manifest_rows),
        "completed_batches": completed_batches,
        "failed_batches": failed_batches,
        "total_batches": len(batches),
        "manifest_path": str(manifest_path),
        "report_path": str(report_path),
        "counterfactual_path": str(counterfactual_path),
        "output_path": str(output_path),
    }
