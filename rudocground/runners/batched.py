from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
import json
import os
import time

from ..models import PromptTask
from ..providers.ollama_provider import OllamaProvider
from ..runner import evaluate_run, load_prompt_tasks


@dataclass(frozen=True)
class BatchSpec:
    case_id: str
    variant_id: str
    label: str
    strategy: str
    tasks: list[PromptTask]
    prompt: str
    schema: dict[str, Any]
    estimated_tokens: int
    num_ctx: int
    num_predict: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def question_ids(self) -> list[str]:
        return [task.question_id for task in self.tasks]

    @property
    def key(self) -> str:
        return f"{self.case_id}|{self.variant_id}|{self.label}"


class BatchedProtocol(Protocol):
    name: str
    system_prompt: str

    def build_batches(
        self,
        tasks: list[PromptTask],
        *,
        gold_path: Path,
        default_num_ctx: int,
        default_num_predict: int,
    ) -> list[BatchSpec]: ...

    def decode_response(
        self,
        *,
        batch: BatchSpec,
        parsed: dict[str, Any],
        provider: OllamaProvider,
        request_body: dict[str, Any],
        response_body: dict[str, Any],
        latency_ms: int,
        batch_response_path: str,
    ) -> list[dict[str, Any]]: ...

    def postprocess_report(
        self,
        report: dict[str, Any],
        *,
        gold_path: Path,
        predictions_path: Path,
    ) -> dict[str, Any]: ...

    def postprocess_csv(self, csv_path: Path, report: dict[str, Any]) -> None: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSONL row") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{lineno}: JSONL row is not an object")
            rows.append(row)
    return rows


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
            os.fsync(handle.fileno())
        except OSError:
            pass


def _successful_keys(path: Path) -> set[tuple[str, str, str]]:
    return {
        (str(row.get("case_id")), str(row.get("variant_id")), str(row.get("question_id")))
        for row in _load_jsonl(path)
        if row.get("status") == "ok"
    }


def _sort_predictions(path: Path) -> None:
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _load_jsonl(path):
        key = (str(row.get("case_id")), str(row.get("variant_id")), str(row.get("question_id")))
        latest[key] = row
    rows = [latest[key] for key in sorted(latest)]
    path.write_text("", encoding="utf-8")
    _append_jsonl(path, rows)


def _write_manifest(
    path: Path,
    *,
    status: str,
    protocol: BatchedProtocol,
    model: str,
    base_url: str,
    temperature: float,
    seed: int,
    keep_alive: str,
    prompts_path: Path,
    gold_path: Path,
    output_path: Path,
    report_path: Path,
    counterfactual_path: Path,
    batches: dict[str, Any],
    total_batches: int,
    completed_batches: int,
    failed_batches: int,
    total_attempts: int,
    rows_written: int,
) -> None:
    payload = {
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "status": status,
        "protocol": protocol.name,
        "model": model,
        "provider": "ollama",
        "base_url": base_url,
        "temperature": temperature,
        "seed": seed,
        "keep_alive": keep_alive,
        "prompt_sha256": _sha256_file(prompts_path),
        "gold_sha256": _sha256_file(gold_path),
        "output_sha256": _sha256_file(output_path) if output_path.exists() else None,
        "report_sha256": _sha256_file(report_path) if report_path.exists() else None,
        "counterfactual_sha256": _sha256_file(counterfactual_path) if counterfactual_path.exists() else None,
        "batches": batches,
        "rows_written": rows_written,
        "completed_batches": completed_batches,
        "failed_batches": failed_batches,
        "total_batches": total_batches,
        "total_attempts": total_attempts,
    }
    _write_json(path, payload)


def run_batched(
    *,
    protocol: BatchedProtocol,
    prompts_path: str | Path,
    gold_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
    counterfactual_path: str | Path,
    manifest_path: str | Path,
    model: str = "qwen3:8b",
    base_url: str = "http://127.0.0.1:11434/api/chat",
    default_num_ctx: int = 16384,
    default_num_predict: int = 1024,
    temperature: float = 0.0,
    seed: int = 42,
    keep_alive: str = "30m",
    resume: bool = False,
    dry_run: bool = False,
    max_attempts: int = 3,
) -> dict[str, Any]:
    prompts_path = Path(prompts_path)
    gold_path = Path(gold_path)
    output_path = Path(output_path)
    report_path = Path(report_path)
    counterfactual_path = Path(counterfactual_path)
    manifest_path = Path(manifest_path)

    tasks = load_prompt_tasks(prompts_path)
    batches = protocol.build_batches(
        tasks,
        gold_path=gold_path,
        default_num_ctx=default_num_ctx,
        default_num_predict=default_num_predict,
    )

    if dry_run:
        return {
            "status": "dry_run",
            "protocol": protocol.name,
            "task_count": len(tasks),
            "batch_count": len(batches),
            "output_path": str(output_path),
            "report_path": str(report_path),
            "counterfactual_path": str(counterfactual_path),
            "manifest_path": str(manifest_path),
        }

    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    batches_dir = output_path.parent / f"{output_path.stem}_batches"
    batches_dir.mkdir(parents=True, exist_ok=True)

    existing = _successful_keys(output_path) if resume else set()
    if not resume:
        output_path.write_text("", encoding="utf-8")

    row_keys = set(existing)
    batch_status: dict[str, Any] = {}
    completed_batches = 0
    failed_batches = 0
    total_attempts = 0

    for batch in batches:
        if all((batch.case_id, batch.variant_id, question_id) in existing for question_id in batch.question_ids):
            batch_status[batch.key] = {
                "status": "completed",
                "attempts": 0,
                "skipped": True,
                "completed_at": _utc_now(),
                "strategy": batch.strategy,
                "question_ids": batch.question_ids,
                "estimated_tokens": batch.estimated_tokens,
                "num_ctx": batch.num_ctx,
                "num_predict": batch.num_predict,
            }
            continue

        provider = OllamaProvider(
            model=model,
            base_url=base_url,
            temperature=temperature,
            seed=seed,
            keep_alive=keep_alive,
            stream=False,
            think=False,
            num_ctx=batch.num_ctx,
            num_predict=batch.num_predict,
            max_retries=1,
        )
        response_path = batches_dir / f"{batch.key.replace('|', '__')}.json"
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            total_attempts += 1
            started = perf_counter()
            try:
                result = provider._chat(
                    system_prompt=protocol.system_prompt,
                    user_prompt=batch.prompt,
                    response_schema=batch.schema,
                )
                latency_ms = int((perf_counter() - started) * 1000)
                parsed = result.parsed_payload
                if not isinstance(parsed, dict):
                    raise RuntimeError("batched response is not a JSON object")
                if set(parsed) != set(batch.question_ids):
                    missing = sorted(set(batch.question_ids) - set(parsed))
                    extra = sorted(set(parsed) - set(batch.question_ids))
                    raise RuntimeError(f"batch key mismatch missing={missing[:5]} extra={extra[:5]}")

                decoded = protocol.decode_response(
                    batch=batch,
                    parsed=parsed,
                    provider=provider,
                    request_body=result.request_body,
                    response_body=result.response_body,
                    latency_ms=latency_ms,
                    batch_response_path=str(response_path),
                )
                decoded_keys = {
                    (str(row["case_id"]), str(row["variant_id"]), str(row["question_id"]))
                    for row in decoded
                }
                expected_keys = {(batch.case_id, batch.variant_id, question_id) for question_id in batch.question_ids}
                if decoded_keys != expected_keys:
                    raise RuntimeError("protocol decoder returned a different task set")

                new_rows = [
                    row
                    for row in decoded
                    if (str(row["case_id"]), str(row["variant_id"]), str(row["question_id"])) not in row_keys
                ]
                _append_jsonl(output_path, new_rows)
                row_keys.update(decoded_keys)
                _write_json(
                    response_path,
                    {
                        "batch_id": batch.key,
                        "case_id": batch.case_id,
                        "variant_id": batch.variant_id,
                        "label": batch.label,
                        "strategy": batch.strategy,
                        "question_ids": batch.question_ids,
                        "request": result.request_body,
                        "response": result.response_body,
                        "parsed_response": parsed,
                        "latency_ms": latency_ms,
                        "prompt_eval_count": result.prompt_eval_count,
                        "eval_count": result.eval_count,
                    },
                )
                completed_batches += 1
                batch_status[batch.key] = {
                    "status": "completed",
                    "attempts": attempt,
                    "completed_at": _utc_now(),
                    "strategy": batch.strategy,
                    "question_ids": batch.question_ids,
                    "estimated_tokens": batch.estimated_tokens,
                    "num_ctx": batch.num_ctx,
                    "num_predict": batch.num_predict,
                    "response_path": str(response_path),
                }
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if attempt < max_attempts:
                    time.sleep(min(2 ** (attempt - 1), 8))

        if last_error is not None:
            failed_batches += 1
            batch_status[batch.key] = {
                "status": "failed",
                "attempts": max_attempts,
                "failed_at": _utc_now(),
                "strategy": batch.strategy,
                "question_ids": batch.question_ids,
                "estimated_tokens": batch.estimated_tokens,
                "num_ctx": batch.num_ctx,
                "num_predict": batch.num_predict,
                "error": str(last_error),
            }

        _write_manifest(
            manifest_path,
            status="running",
            protocol=protocol,
            model=model,
            base_url=base_url,
            temperature=temperature,
            seed=seed,
            keep_alive=keep_alive,
            prompts_path=prompts_path,
            gold_path=gold_path,
            output_path=output_path,
            report_path=report_path,
            counterfactual_path=counterfactual_path,
            batches=batch_status,
            total_batches=len(batches),
            completed_batches=completed_batches,
            failed_batches=failed_batches,
            total_attempts=total_attempts,
            rows_written=len(row_keys),
        )

    _sort_predictions(output_path)
    report = evaluate_run(gold_path, output_path, report_path)
    report = protocol.postprocess_report(report, gold_path=gold_path, predictions_path=output_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    protocol.postprocess_csv(report_path.with_suffix(".csv"), report)
    counterfactual_path.parent.mkdir(parents=True, exist_ok=True)
    counterfactual_path.write_text(json.dumps(report["counterfactual"], ensure_ascii=False, indent=2), encoding="utf-8")

    final_status = "complete" if len(row_keys) == len(tasks) else "incomplete"
    _write_manifest(
        manifest_path,
        status=final_status,
        protocol=protocol,
        model=model,
        base_url=base_url,
        temperature=temperature,
        seed=seed,
        keep_alive=keep_alive,
        prompts_path=prompts_path,
        gold_path=gold_path,
        output_path=output_path,
        report_path=report_path,
        counterfactual_path=counterfactual_path,
        batches=batch_status,
        total_batches=len(batches),
        completed_batches=completed_batches,
        failed_batches=failed_batches,
        total_attempts=total_attempts,
        rows_written=len(row_keys),
    )

    return {
        "status": final_status,
        "protocol": protocol.name,
        "task_count": len(tasks),
        "batch_count": len(batches),
        "completed_batches": completed_batches,
        "failed_batches": failed_batches,
        "rows_written": len(row_keys),
        "output_path": str(output_path),
        "report_path": str(report_path),
        "counterfactual_path": str(counterfactual_path),
        "manifest_path": str(manifest_path),
        "overall": report["overall"],
    }
