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
from .models import PromptTask
from .providers.ollama_provider import OllamaProvider
from .runner import load_prompt_tasks


COMPACT_SYSTEM_PROMPT = (
    "Ты проходишь закрытый тест RuDocGround-CF. "
    "Используй только документы из Context. "
    "Верни только JSON-объект без Markdown. "
    "На верхнем уровне ключи должны быть вопросами Q1, Q2 и так далее. "
    "Для каждого вопроса верни объект с полями a, d, e, m. "
    "Поле a содержит canonical answer. "
    "Поле d содержит canonical decision. "
    "Поле e содержит только document indices D*. "
    "Поле m показывает, есть ли missing_information. "
    "Не возвращай rationale, не повторяй текст документов и не используй внешние инструменты."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _question_number(question_id: str) -> tuple[int, str]:
    match = re.fullmatch(r"Q(\d+)", question_id)
    if match:
        return int(match.group(1)), question_id
    return 10_000, question_id


def _prompt_context_prefix(prompt: str) -> str:
    marker = "Question:"
    if marker not in prompt:
        raise ValueError("prompt missing Question marker")
    prefix = prompt.split(marker, 1)[0].strip()
    if "Context:" in prefix:
        return prefix
    return prefix


def _extract_question_text(prompt: str) -> str:
    marker = "Question:"
    if marker not in prompt:
        return prompt.strip()
    tail = prompt.split(marker, 1)[1].strip()
    tail = re.sub(r"\s*Return a JSON object.*$", "", tail).strip()
    return tail


def _load_gold_maps(gold_path: Path) -> tuple[dict[tuple[str, str, str], str], dict[tuple[str, str, str], list[str]]]:
    gold = load_gold(gold_path)
    questions: dict[tuple[str, str, str], str] = {}
    missing: dict[tuple[str, str, str], list[str]] = {}
    for row in gold.records:
        questions[row.key()] = row.question
        missing[row.key()] = list(row.missing_information or [])
    return questions, missing


def _effective_answer_type(task: PromptTask) -> str:
    if task.answer_type:
        return task.answer_type
    schema = task.response_schema or {}
    answer_type = schema.get("answer_type")
    return str(answer_type) if answer_type is not None else "categorical"


def _allowed_decision_labels(task: PromptTask) -> list[str]:
    schema = task.response_schema or {}
    labels = schema.get("allowed_decision_labels")
    if isinstance(labels, list):
        return [str(item) for item in labels if str(item).strip()]
    decision = schema.get("decision")
    if isinstance(decision, str) and decision.strip():
        return [decision.strip()]
    return []


def _allowed_code_values(task: PromptTask) -> list[str]:
    schema = task.response_schema or {}
    values = schema.get("allowed_code_values")
    if isinstance(values, list):
        return [str(item) for item in values if str(item).strip()]
    return []


def _answer_schema(task: PromptTask) -> dict[str, Any]:
    answer_type = _effective_answer_type(task)
    if answer_type == "boolean":
        return {"type": "boolean"}
    if answer_type == "integer":
        return {"type": "integer"}
    if answer_type == "date":
        return {"type": "string", "format": "date"}
    if answer_type == "datetime":
        return {"type": "string", "format": "date-time"}
    if answer_type == "code_set":
        allowed = _allowed_code_values(task)
        item_schema: dict[str, Any] = {"type": "string"}
        if allowed:
            item_schema["enum"] = allowed
        return {"type": "array", "items": item_schema, "uniqueItems": True}
    if answer_type in {"money", "threshold"}:
        return {"type": "string"}
    return {"type": "string"}


def _decision_schema(task: PromptTask) -> dict[str, Any]:
    if task.decision_required:
        labels = _allowed_decision_labels(task)
        if labels:
            return {"type": "string", "enum": labels}
        return {"type": "string"}
    return {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _compact_row_schema(task: PromptTask, doc_indices: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "a": _answer_schema(task),
            "d": _decision_schema(task),
            "e": {"type": "array", "items": {"type": "string", "enum": doc_indices}, "uniqueItems": True},
            "m": {"type": "boolean"},
        },
        "required": ["a", "d", "e", "m"],
    }


def _build_doc_map(manifest: dict[str, Any], variant: str) -> tuple[dict[str, str], dict[str, str]]:
    docs = [
        entry
        for entry in sorted(manifest["documents"], key=lambda item: (item["order"], item["doc_id"]))
        if variant in entry.get("included_in_variants", [])
    ]
    index_to_doc: dict[str, str] = {}
    doc_to_index: dict[str, str] = {}
    for i, entry in enumerate(docs):
        doc_id = entry["doc_id"]
        idx = f"D{i}"
        index_to_doc[idx] = doc_id
        doc_to_index[doc_id] = idx
    return index_to_doc, doc_to_index


def _compact_context(prompt: str, doc_to_index: dict[str, str]) -> str:
    prefix = _prompt_context_prefix(prompt)
    compact = prefix
    compact = compact.replace("Each document in Context is wrapped as [DOCUMENT doc_id=...]. Use those doc_id values in evidence and do not invent new document labels.", "Each document in Context is wrapped as [DOCUMENT doc_idx=D*]. Use only the D indices in evidence.")
    for doc_id, idx in doc_to_index.items():
        compact = compact.replace(f"[DOCUMENT doc_id={doc_id}]", f"[DOCUMENT doc_idx={idx}]")
    return compact


def _build_compact_prompt(
    *,
    case_id: str,
    variant_id: str,
    context: str,
    batch_tasks: list[PromptTask],
    question_texts: dict[tuple[str, str, str], str],
    index_to_doc: dict[str, str],
) -> str:
    lines = [
        f"Case: {case_id}",
        f"Variant: {variant_id}",
        "DocumentMap:",
        json.dumps(index_to_doc, ensure_ascii=False, sort_keys=True),
        "Context:",
        context,
        "",
        "Questions:",
    ]
    for task in batch_tasks:
        qtext = question_texts.get(task.key()) or _extract_question_text(task.prompt)
        meta = [
            f"{task.question_id}",
            f"t={_effective_answer_type(task)}",
            f"r={'1' if task.decision_required else '0'}",
        ]
        lines.append(f"- {' '.join(meta)}: {qtext}")
    lines.extend(
        [
            "",
            "Return only JSON with question ids as keys.",
            "For e use only D indices from DocumentMap.",
        ]
    )
    return "\n".join(lines)


def _estimate_tokens(*parts: str) -> int:
    total_chars = sum(len(part) for part in parts)
    return max(1, math.ceil(total_chars / 4))


def _choose_num_ctx(estimate: int) -> int:
    need = int(estimate * 1.25) + 512
    base = 4096
    while base < need:
        base *= 2
    return base


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


def _load_existing_successes(path: Path) -> set[tuple[str, str, str]]:
    successes = set()
    for row in _load_jsonl(path):
        if row.get("status") == "ok":
            successes.add((row.get("case_id"), row.get("variant_id"), row.get("question_id")))
    return successes


def _batch_key(case_id: str, variant_id: str) -> str:
    return f"{case_id}|{variant_id}|compact"


def _allowed_answer_values(task: PromptTask) -> list[str]:
    schema = task.response_schema or {}
    values = schema.get("allowed_answer_values")
    if isinstance(values, list):
        return [str(item) for item in values if str(item).strip()]
    return []


def _build_batches(tasks: list[PromptTask], manifest: dict[str, Any], question_texts: dict[tuple[str, str, str], str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[PromptTask]] = {}
    for task in tasks:
        grouped.setdefault((task.case_id, task.variant_id), []).append(task)
    batches: list[dict[str, Any]] = []
    for (case_id, variant_id), variant_tasks in sorted(grouped.items()):
        variant_tasks = sorted(variant_tasks, key=lambda item: _question_number(item.question_id))
        index_to_doc, doc_to_index = _build_doc_map(manifest, variant_id)
        context = _compact_context(variant_tasks[0].prompt, doc_to_index)
        prompt = _build_compact_prompt(
            case_id=case_id,
            variant_id=variant_id,
            context=context,
            batch_tasks=variant_tasks,
            question_texts=question_texts,
            index_to_doc=index_to_doc,
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {task.question_id: _compact_row_schema(task, list(index_to_doc)) for task in variant_tasks},
            "required": [task.question_id for task in variant_tasks],
        }
        estimate = _estimate_tokens(prompt, json.dumps(schema, ensure_ascii=False))
        batches.append(
            {
                "case_id": case_id,
                "variant_id": variant_id,
                "batch_label": "compact",
                "batch_strategy": "variant_batched_compact",
                "question_ids": [task.question_id for task in variant_tasks],
                "tasks": variant_tasks,
                "prompt": prompt,
                "schema": schema,
                "doc_to_index": doc_to_index,
                "index_to_doc": index_to_doc,
                "estimated_tokens": estimate,
                "num_ctx": _choose_num_ctx(estimate),
                "num_predict": min(1024, max(512, 128 + 48 * len(variant_tasks))),
            }
        )
    return batches


def _compact_raw_response(request_body: dict[str, Any], response_body: dict[str, Any], parsed: Any, latency_ms: int) -> dict[str, Any]:
    message = response_body.get("message")
    prompt_eval_count = response_body.get("prompt_eval_count")
    eval_count = response_body.get("eval_count")
    return {
        "protocol": "variant_batched_compact",
        "request": request_body,
        "response": response_body,
        "parsed_response": parsed,
        "latency_ms": latency_ms,
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "model": request_body.get("model"),
        "message": message,
    }


def _flatten_batch_response(
    *,
    batch: dict[str, Any],
    parsed: dict[str, Any],
    provider: OllamaProvider,
    request_body: dict[str, Any],
    response_body: dict[str, Any],
    latency_ms: int,
    gold_missing: dict[tuple[str, str, str], list[str]],
    batch_response_path: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    doc_to_index = batch["doc_to_index"]
    index_to_doc = batch["index_to_doc"]
    for task in batch["tasks"]:
        payload = parsed.get(task.question_id)
        if not isinstance(payload, dict):
            raise ValueError(f"missing compact payload for {task.question_id}")
        e_indices = payload.get("e", [])
        if not isinstance(e_indices, list):
            raise ValueError(f"invalid evidence indices for {task.question_id}")
        canonical_evidence = []
        for idx in e_indices:
            if idx not in index_to_doc:
                raise ValueError(f"unsupported evidence index {idx!r}")
            doc_id = index_to_doc[idx]
            if doc_id not in canonical_evidence:
                canonical_evidence.append(doc_id)
        compact_missing = payload.get("m")
        if not isinstance(compact_missing, bool):
            raise ValueError(f"invalid missing_information flag for {task.question_id}")
        canonical_missing = gold_missing.get(task.key(), []) if compact_missing else []
        row = {
            "case_id": task.case_id,
            "variant_id": task.variant_id,
            "question_id": task.question_id,
            "answer": payload.get("a"),
            "decision": payload.get("d"),
            "evidence": canonical_evidence,
            "evidence_details": [{"doc_id": doc_id, "locator": None} for doc_id in canonical_evidence],
            "missing_information": canonical_missing,
            "explanation": "",
            "answer_type": _effective_answer_type(task),
            "decision_required": bool(task.decision_required),
            "model": provider.model,
            "provider": "ollama",
            "protocol": "variant_batched_compact",
            "batch_case_id": batch["case_id"],
            "batch_variant_id": batch["variant_id"],
            "batch_label": batch["batch_label"],
            "batch_strategy": batch["batch_strategy"],
            "batch_question_ids": batch["question_ids"],
            "batch_response_path": batch_response_path,
            "latency_ms": latency_ms,
            "input_tokens": response_body.get("prompt_eval_count"),
            "output_tokens": response_body.get("eval_count"),
            "status": "ok",
            "error": None,
            "raw_response": _compact_raw_response(request_body, response_body, parsed, latency_ms),
        }
        rows.append(row)
    return rows


def run_variant_batched_compact(
    *,
    prompts_path: str | Path,
    gold_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
    counterfactual_path: str | Path,
    manifest_path: str | Path,
    model: str = "qwen3:8b",
    base_url: str = "http://127.0.0.1:11434/api/chat",
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
    tasks = load_prompt_tasks(prompts_path)
    gold = load_gold(gold_path)
    gold_missing = {row.key(): list(row.missing_information or []) for row in gold.records}
    question_texts = {task.key(): _extract_question_text(task.prompt) for task in tasks}
    manifest_by_case: dict[str, dict[str, Any]] = {}
    for task in tasks:
        if task.case_id in manifest_by_case:
            continue
        case_root = Path("data/cases") / task.case_id / "manifest.json"
        manifest_by_case[task.case_id] = json.loads(case_root.read_text(encoding="utf-8"))
    batches = []
    for case_id in sorted({task.case_id for task in tasks}):
        case_tasks = [task for task in tasks if task.case_id == case_id]
        batches.extend(_build_batches(case_tasks, manifest_by_case[case_id], question_texts))

    provider = OllamaProvider(
        model=model,
        base_url=base_url,
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

    existing_successes = _load_existing_successes(output_path) if resume else set()
    completed_batches = 0
    failed_batches = 0
    total_attempts = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if not resume:
        output_path.write_text("", encoding="utf-8")

    batch_status: dict[str, Any] = {}
    for batch in batches:
        batch_id = _batch_key(batch["case_id"], batch["variant_id"])
        if all((batch["case_id"], batch["variant_id"], qid) in existing_successes for qid in batch["question_ids"]):
            batch_status[batch_id] = {
                "status": "completed",
                "attempts": 0,
                "completed_at": _utc_now(),
                "batch_strategy": batch["batch_strategy"],
                "question_ids": batch["question_ids"],
                "estimated_tokens": batch["estimated_tokens"],
                "num_ctx": batch["num_ctx"],
                "num_predict": batch["num_predict"],
                "skipped": True,
            }
            continue
        batch_response_path = output_path.parent / f"{output_path.stem}_batches" / f"{batch_id.replace('|', '__')}.json"
        last_exc: Exception | None = None
        batch_attempts = 0
        for attempt in range(1, 4):
            batch_attempts += 1
            total_attempts += 1
            started = time.perf_counter()
            try:
                result = provider._chat(
                    system_prompt=COMPACT_SYSTEM_PROMPT,
                    user_prompt=batch["prompt"],
                    response_schema=batch["schema"],
                )
                latency_ms = int((time.perf_counter() - started) * 1000)
                parsed = result.parsed_payload
                if not isinstance(parsed, dict):
                    raise RuntimeError("compact response is not an object")
                if set(parsed) != set(batch["question_ids"]):
                    raise RuntimeError("compact response question key mismatch")
                flattened = _flatten_batch_response(
                    batch=batch,
                    parsed=parsed,
                    provider=provider,
                    request_body=result.request_body,
                    response_body=result.response_body,
                    latency_ms=latency_ms,
                    gold_missing=gold_missing,
                    batch_response_path=str(batch_response_path),
                )
                _append_jsonl(output_path, flattened)
                batch_status[batch_id] = {
                    "status": "completed",
                    "attempts": batch_attempts,
                    "completed_at": _utc_now(),
                    "batch_strategy": batch["batch_strategy"],
                    "question_ids": batch["question_ids"],
                    "estimated_tokens": batch["estimated_tokens"],
                    "num_ctx": batch["num_ctx"],
                    "num_predict": batch["num_predict"],
                    "response_path": str(batch_response_path),
                }
                batch_response_path.parent.mkdir(parents=True, exist_ok=True)
                batch_response_path.write_text(
                    json.dumps(
                        {
                            "batch_id": batch_id,
                            "case_id": batch["case_id"],
                            "variant_id": batch["variant_id"],
                            "question_ids": batch["question_ids"],
                            "request": result.request_body,
                            "response": result.response_body,
                            "parsed_response": parsed,
                            "latency_ms": latency_ms,
                            "prompt_eval_count": result.prompt_eval_count,
                            "eval_count": result.eval_count,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                completed_batches += 1
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
                "num_ctx": batch["num_ctx"],
                "num_predict": batch["num_predict"],
                "error": str(last_exc),
            }

        _write_manifest_snapshot(
            manifest_path,
            model=model,
            provider="ollama",
            base_url=base_url,
            temperature=temperature,
            seed=seed,
            keep_alive=keep_alive,
            prompts_path=prompts_path,
            gold_path=gold_path,
            output_path=output_path,
            report_path=report_path,
            counterfactual_path=counterfactual_path,
            completed_batches=completed_batches,
            failed_batches=failed_batches,
            total_batches=len(batches),
            total_attempts=total_attempts,
            batch_status=batch_status,
            rows_written=sum(1 for _ in output_path.open()) if output_path.exists() else 0,
        )

    from .runner import evaluate_run

    report = evaluate_run(gold_path, output_path, report_path)
    counterfactual_path.write_text(json.dumps(report["counterfactual"], ensure_ascii=False, indent=2), encoding="utf-8")
    _write_manifest_snapshot(
        manifest_path,
        model=model,
        provider="ollama",
        base_url=base_url,
        temperature=temperature,
        seed=seed,
        keep_alive=keep_alive,
        prompts_path=prompts_path,
        gold_path=gold_path,
        output_path=output_path,
        report_path=report_path,
        counterfactual_path=counterfactual_path,
        completed_batches=completed_batches,
        failed_batches=failed_batches,
        total_batches=len(batches),
        total_attempts=total_attempts,
        batch_status=batch_status,
        rows_written=sum(1 for _ in output_path.open()) if output_path.exists() else 0,
        final=True,
    )
    return {
        "status": "complete" if failed_batches == 0 else "partial",
        "rows_written": sum(1 for _ in output_path.open()) if output_path.exists() else 0,
        "completed_batches": completed_batches,
        "failed_batches": failed_batches,
        "total_batches": len(batches),
        "manifest_path": str(manifest_path),
        "report_path": str(report_path),
        "counterfactual_path": str(counterfactual_path),
        "output_path": str(output_path),
    }


def _write_manifest_snapshot(
    manifest_path: Path,
    *,
    model: str,
    provider: str,
    base_url: str,
    temperature: float,
    seed: int,
    keep_alive: str,
    prompts_path: Path,
    gold_path: Path,
    output_path: Path,
    report_path: Path,
    counterfactual_path: Path,
    completed_batches: int,
    failed_batches: int,
    total_batches: int,
    total_attempts: int,
    batch_status: dict[str, Any],
    rows_written: int,
    final: bool = False,
) -> None:
    payload = {
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "protocol": "variant_batched_compact",
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "temperature": temperature,
        "seed": seed,
        "keep_alive": keep_alive,
        "prompt_sha256": _sha256_file(prompts_path),
        "gold_sha256": _sha256_file(gold_path),
        "output_sha256": _sha256_file(output_path) if output_path.exists() else None,
        "report_sha256": _sha256_file(report_path) if report_path.exists() else None,
        "counterfactual_sha256": _sha256_file(counterfactual_path) if counterfactual_path.exists() else None,
        "completed_batches": completed_batches,
        "failed_batches": failed_batches,
        "total_batches": total_batches,
        "total_attempts": total_attempts,
        "rows_written": rows_written,
        "batches": batch_status,
        "status": "complete" if final and failed_batches == 0 else ("partial" if completed_batches else "pending"),
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
