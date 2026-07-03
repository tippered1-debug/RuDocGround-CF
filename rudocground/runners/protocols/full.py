from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import math
import re

from ...io import load_gold
from ...models import PromptTask, coerce_output_answer
from ...providers.ollama_provider import OllamaProvider
from ..batched import BatchSpec


class FullBatchedProtocol:
    name = "variant_batched"
    system_prompt = (
        "Ты проходишь закрытый тест RuDocGround-CF. "
        "Используй только документы из Context. "
        "Верни только JSON-объект без Markdown. "
        "Верхний уровень ответа должен содержать ключи всех вопросов из списка. "
        "Для каждого вопроса верни объект с полями answer, decision, evidence, evidence_details, missing_information, explanation. "
        "Для boolean верни JSON boolean. "
        "Для code_set верни массив canonical codes, а не pipe-joined string. "
        "Не используй семантическую нормализацию и не выдумывай документы."
    )

    @staticmethod
    def _question_number(question_id: str) -> tuple[int, str]:
        match = re.fullmatch(r"Q(\d+)", question_id)
        return (int(match.group(1)), question_id) if match else (10_000, question_id)

    @staticmethod
    def _context(prompt: str) -> str:
        marker = "Context:"
        if marker not in prompt:
            raise ValueError("prompt missing Context section")
        return prompt.split(marker, 1)[1].strip()

    @staticmethod
    def _answer_type(task: PromptTask) -> str:
        return task.answer_type or str((task.response_schema or {}).get("answer_type") or "categorical")

    @staticmethod
    def _list_schema_value(task: PromptTask, key: str) -> list[str]:
        values = (task.response_schema or {}).get(key)
        return [str(item) for item in values if str(item).strip()] if isinstance(values, list) else []

    def _answer_schema(self, task: PromptTask) -> dict[str, Any]:
        answer_type = self._answer_type(task)
        allowed_answers = self._list_schema_value(task, "allowed_answer_values")
        if allowed_answers:
            return {"type": "string", "enum": allowed_answers}
        if answer_type == "boolean":
            return {"type": "boolean"}
        if answer_type == "integer":
            return {"type": "integer"}
        if answer_type == "money":
            return {"anyOf": [{"type": "number"}, {"type": "string"}]}
        if answer_type == "code_set":
            allowed_codes = self._list_schema_value(task, "allowed_code_values")
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
        return {"type": "string"}

    def _decision_schema(self, task: PromptTask) -> dict[str, Any]:
        if not task.decision_required:
            return {"anyOf": [{"type": "string"}, {"type": "null"}]}
        labels = self._list_schema_value(task, "allowed_decision_labels")
        if not labels:
            decision = (task.response_schema or {}).get("decision")
            labels = [str(decision)] if isinstance(decision, str) and decision.strip() else []
        return {"type": "string", "enum": labels} if labels else {"type": "string"}

    def _question_schema(self, task: PromptTask) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "answer": self._answer_schema(task),
                "decision": self._decision_schema(task),
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

    def _schema(self, tasks: list[PromptTask]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {task.question_id: self._question_schema(task) for task in tasks},
            "required": [task.question_id for task in tasks],
        }

    def _prompt(
        self,
        case_id: str,
        variant_id: str,
        context: str,
        tasks: list[PromptTask],
        questions: dict[tuple[str, str, str], str],
    ) -> str:
        lines = [f"Case ID: {case_id}", f"Variant ID: {variant_id}", "Context:", context, "", "Questions:"]
        for task in tasks:
            meta = [
                f"answer_type={self._answer_type(task)}",
                f"decision_required={str(bool(task.decision_required)).lower()}",
            ]
            decisions = self._list_schema_value(task, "allowed_decision_labels")
            codes = self._list_schema_value(task, "allowed_code_values")
            answers = self._list_schema_value(task, "allowed_answer_values")
            if decisions:
                meta.append(f"allowed_decisions={json.dumps(decisions, ensure_ascii=False)}")
            if codes:
                meta.append(f"allowed_codes={json.dumps(codes, ensure_ascii=False)}")
            if answers:
                meta.append(f"allowed_answers={json.dumps(answers, ensure_ascii=False)}")
            lines.append(f"- {task.question_id} | {'; '.join(meta)}: {questions.get(task.key(), '')}")
        lines.extend(["", "Return an object with one top-level key per question id.", "For code_set answers, return JSON arrays of canonical codes.", "Do not add extra keys."])
        return "\n".join(lines)

    @staticmethod
    def _estimate_tokens(*parts: str) -> int:
        return max(1, math.ceil(sum(len(part) for part in parts) / 4))

    def build_batches(
        self,
        tasks: list[PromptTask],
        *,
        gold_path: Path,
        default_num_ctx: int,
        default_num_predict: int,
    ) -> list[BatchSpec]:
        gold = load_gold(gold_path)
        questions = {row.key(): row.question for row in gold.records}
        grouped: dict[tuple[str, str], list[PromptTask]] = {}
        for task in tasks:
            grouped.setdefault((task.case_id, task.variant_id), []).append(task)

        batches: list[BatchSpec] = []
        for (case_id, variant_id), variant_tasks in sorted(grouped.items()):
            variant_tasks.sort(key=lambda task: self._question_number(task.question_id))
            context = self._context(variant_tasks[0].prompt)
            full_prompt = self._prompt(case_id, variant_id, context, variant_tasks, questions)
            full_schema = self._schema(variant_tasks)
            estimate = self._estimate_tokens(full_prompt, json.dumps(full_schema, ensure_ascii=False))
            chunks = [variant_tasks]
            strategy = "variant_batched"
            if estimate > int(default_num_ctx * 0.85) and len(variant_tasks) > 7:
                chunks = [variant_tasks[index : index + 7] for index in range(0, len(variant_tasks), 7)]
                strategy = "split_7"

            for index, chunk in enumerate(chunks, start=1):
                prompt = self._prompt(case_id, variant_id, context, chunk, questions)
                schema = self._schema(chunk)
                chunk_estimate = self._estimate_tokens(prompt, json.dumps(schema, ensure_ascii=False))
                batches.append(
                    BatchSpec(
                        case_id=case_id,
                        variant_id=variant_id,
                        label="full" if len(chunks) == 1 else f"part{index}",
                        strategy=strategy,
                        tasks=chunk,
                        prompt=prompt,
                        schema=schema,
                        estimated_tokens=chunk_estimate,
                        num_ctx=default_num_ctx,
                        num_predict=default_num_predict,
                    )
                )
        return batches

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
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for task in batch.tasks:
            payload = parsed.get(task.question_id)
            if not isinstance(payload, dict):
                raise ValueError(f"missing structured payload for {task.question_id}")
            rows.append(
                {
                    "case_id": task.case_id,
                    "variant_id": task.variant_id,
                    "question_id": task.question_id,
                    "answer": coerce_output_answer(self._answer_type(task), payload.get("answer")),
                    "decision": payload.get("decision"),
                    "evidence": payload.get("evidence", []),
                    "evidence_details": payload.get("evidence_details", []),
                    "missing_information": payload.get("missing_information", []),
                    "explanation": payload.get("explanation", ""),
                    "answer_type": self._answer_type(task),
                    "decision_required": bool(task.decision_required),
                    "model": provider.model,
                    "provider": "ollama",
                    "protocol": self.name,
                    "batch_case_id": batch.case_id,
                    "batch_variant_id": batch.variant_id,
                    "batch_label": batch.label,
                    "batch_strategy": batch.strategy,
                    "batch_question_ids": batch.question_ids,
                    "batch_response_path": batch_response_path,
                    "latency_ms": latency_ms,
                    "input_tokens": response_body.get("prompt_eval_count"),
                    "output_tokens": response_body.get("eval_count"),
                    "status": "ok",
                    "error": None,
                    "raw_response": {
                        "request": request_body,
                        "response": response_body,
                        "parsed_response": parsed,
                    },
                }
            )
        return rows

    def postprocess_report(self, report: dict[str, Any], *, gold_path: Path, predictions_path: Path) -> dict[str, Any]:
        report.setdefault("metric_contracts", {})["missing_information"] = "exact_set_match"
        return report

    def postprocess_csv(self, csv_path: Path, report: dict[str, Any]) -> None:
        return None
