from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import csv
import json
import math
import re

from ...io import load_gold
from ...models import PromptTask, normalize_evidence
from ...providers.ollama_provider import OllamaProvider
from ..batched import BatchSpec


class CompactBatchedProtocol:
    name = "variant_batched_compact"
    system_prompt = (
        "Ты проходишь закрытый тест RuDocGround-CF. "
        "Используй только документы из Context. "
        "Верни только JSON-объект без Markdown. "
        "На верхнем уровне ключи должны быть вопросами Q1, Q2 и так далее. "
        "Для каждого вопроса верни объект с полями a, d, e, m. "
        "Поле a содержит canonical answer. "
        "Поле d содержит canonical decision. "
        "Поле e содержит только document indices D*. "
        "Поле m — boolean: отсутствует ли в пакете информация, необходимая для ответа. "
        "Не возвращай rationale, не повторяй текст документов и не используй внешние инструменты."
    )

    @staticmethod
    def _question_number(question_id: str) -> tuple[int, str]:
        match = re.fullmatch(r"Q(\d+)", question_id)
        return (int(match.group(1)), question_id) if match else (10_000, question_id)

    @staticmethod
    def _answer_type(task: PromptTask) -> str:
        return task.answer_type or str((task.response_schema or {}).get("answer_type") or "categorical")

    @staticmethod
    def _list_schema_value(task: PromptTask, key: str) -> list[str]:
        values = (task.response_schema or {}).get(key)
        return [str(item) for item in values if str(item).strip()] if isinstance(values, list) else []

    @staticmethod
    def _prompt_context_prefix(prompt: str) -> str:
        marker = "Question:"
        if marker not in prompt:
            raise ValueError("prompt missing Question marker")
        return prompt.split(marker, 1)[0].strip()

    @staticmethod
    def _extract_question_text(prompt: str) -> str:
        marker = "Question:"
        tail = prompt.split(marker, 1)[1].strip() if marker in prompt else prompt.strip()
        return re.sub(r"\s*Return a JSON object.*$", "", tail).strip()

    def _answer_schema(self, task: PromptTask) -> dict[str, Any]:
        answer_type = self._answer_type(task)
        allowed_answers = self._list_schema_value(task, "allowed_answer_values")
        if allowed_answers:
            return {"type": "string", "enum": allowed_answers}
        if answer_type == "boolean":
            return {"type": "boolean"}
        if answer_type == "integer":
            return {"type": "integer"}
        if answer_type == "date":
            return {"type": "string", "format": "date"}
        if answer_type == "datetime":
            return {"type": "string", "format": "date-time"}
        if answer_type == "code_set":
            allowed = self._list_schema_value(task, "allowed_code_values")
            item_schema: dict[str, Any] = {"type": "string"}
            if allowed:
                item_schema["enum"] = allowed
            return {"type": "array", "items": item_schema, "uniqueItems": True}
        return {"type": "string"}

    def _decision_schema(self, task: PromptTask) -> dict[str, Any]:
        if not task.decision_required:
            return {"anyOf": [{"type": "string"}, {"type": "null"}]}
        labels = self._list_schema_value(task, "allowed_decision_labels")
        if not labels:
            decision = (task.response_schema or {}).get("decision")
            labels = [str(decision)] if isinstance(decision, str) and decision.strip() else []
        return {"type": "string", "enum": labels} if labels else {"type": "string"}

    def _row_schema(self, task: PromptTask, doc_indices: list[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "a": self._answer_schema(task),
                "d": self._decision_schema(task),
                "e": {"type": "array", "items": {"type": "string", "enum": doc_indices}, "uniqueItems": True},
                "m": {"type": "boolean"},
            },
            "required": ["a", "d", "e", "m"],
        }

    @staticmethod
    def _doc_map(manifest: dict[str, Any], variant_id: str) -> tuple[dict[str, str], dict[str, str]]:
        entries = [
            entry
            for entry in sorted(manifest["documents"], key=lambda item: (item["order"], item["doc_id"]))
            if variant_id in entry.get("included_in_variants", [])
        ]
        index_to_doc = {f"D{index}": str(entry["doc_id"]) for index, entry in enumerate(entries)}
        return index_to_doc, {doc_id: index for index, doc_id in index_to_doc.items()}

    def _compact_context(self, prompt: str, doc_to_index: dict[str, str]) -> str:
        compact = self._prompt_context_prefix(prompt)
        compact = compact.replace(
            "Each document in Context is wrapped as [DOCUMENT doc_id=...]. Use those doc_id values in evidence and do not invent new document labels.",
            "Each document in Context is wrapped as [DOCUMENT doc_idx=D*]. Use only the D indices in evidence.",
        )
        for doc_id, index in doc_to_index.items():
            compact = compact.replace(f"[DOCUMENT doc_id={doc_id}]", f"[DOCUMENT doc_idx={index}]")
        return compact

    def _prompt(
        self,
        *,
        case_id: str,
        variant_id: str,
        context: str,
        tasks: list[PromptTask],
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
        for task in tasks:
            qtext = question_texts.get(task.key()) or self._extract_question_text(task.prompt)
            lines.append(
                f"- {task.question_id} t={self._answer_type(task)} r={'1' if task.decision_required else '0'}: {qtext}"
            )
        lines.extend(["", "Return only JSON with question ids as keys.", "For e use only D indices from DocumentMap."])
        return "\n".join(lines)

    @staticmethod
    def _estimate_tokens(*parts: str) -> int:
        return max(1, math.ceil(sum(len(part) for part in parts) / 4))

    @staticmethod
    def _choose_num_ctx(estimate: int) -> int:
        required = int(estimate * 1.25) + 512
        value = 4096
        while value < required:
            value *= 2
        return value

    def build_batches(
        self,
        tasks: list[PromptTask],
        *,
        gold_path: Path,
        default_num_ctx: int,
        default_num_predict: int,
    ) -> list[BatchSpec]:
        grouped: dict[tuple[str, str], list[PromptTask]] = {}
        for task in tasks:
            grouped.setdefault((task.case_id, task.variant_id), []).append(task)

        question_texts = {task.key(): self._extract_question_text(task.prompt) for task in tasks}
        manifests: dict[str, dict[str, Any]] = {}
        cases_root = gold_path.parent / "cases"
        batches: list[BatchSpec] = []

        for (case_id, variant_id), variant_tasks in sorted(grouped.items()):
            variant_tasks.sort(key=lambda task: self._question_number(task.question_id))
            if case_id not in manifests:
                manifest_path = cases_root / case_id / "manifest.json"
                manifests[case_id] = json.loads(manifest_path.read_text(encoding="utf-8"))
            index_to_doc, doc_to_index = self._doc_map(manifests[case_id], variant_id)
            context = self._compact_context(variant_tasks[0].prompt, doc_to_index)
            prompt = self._prompt(
                case_id=case_id,
                variant_id=variant_id,
                context=context,
                tasks=variant_tasks,
                question_texts=question_texts,
                index_to_doc=index_to_doc,
            )
            schema = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    task.question_id: self._row_schema(task, list(index_to_doc)) for task in variant_tasks
                },
                "required": [task.question_id for task in variant_tasks],
            }
            estimate = self._estimate_tokens(prompt, json.dumps(schema, ensure_ascii=False))
            batches.append(
                BatchSpec(
                    case_id=case_id,
                    variant_id=variant_id,
                    label="compact",
                    strategy=self.name,
                    tasks=variant_tasks,
                    prompt=prompt,
                    schema=schema,
                    estimated_tokens=estimate,
                    num_ctx=max(default_num_ctx, self._choose_num_ctx(estimate)),
                    num_predict=min(default_num_predict, max(512, 128 + 48 * len(variant_tasks))),
                    metadata={"index_to_doc": index_to_doc},
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
        index_to_doc = batch.metadata["index_to_doc"]
        rows: list[dict[str, Any]] = []
        for task in batch.tasks:
            payload = parsed.get(task.question_id)
            if not isinstance(payload, dict):
                raise ValueError(f"missing compact payload for {task.question_id}")
            indices = payload.get("e", [])
            if not isinstance(indices, list):
                raise ValueError(f"invalid evidence indices for {task.question_id}")
            evidence: list[str] = []
            for index in indices:
                if index not in index_to_doc:
                    raise ValueError(f"unsupported evidence index {index!r}")
                doc_id = index_to_doc[index]
                if doc_id not in evidence:
                    evidence.append(doc_id)
            missing_detected = payload.get("m")
            if not isinstance(missing_detected, bool):
                raise ValueError(f"invalid missing-information flag for {task.question_id}")

            rows.append(
                {
                    "case_id": task.case_id,
                    "variant_id": task.variant_id,
                    "question_id": task.question_id,
                    "answer": payload.get("a"),
                    "decision": payload.get("d"),
                    "evidence": evidence,
                    "evidence_details": [{"doc_id": doc_id, "locator": None} for doc_id in evidence],
                    "missing_information": [],
                    "missing_information_detected": missing_detected,
                    "missing_information_contract": "detection_only",
                    "explanation": "",
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

    @staticmethod
    def _load_predictions(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
        rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                if raw_line.strip():
                    row = json.loads(raw_line)
                    rows[(str(row["case_id"]), str(row["variant_id"]), str(row["question_id"]))] = row
        return rows

    @staticmethod
    def _detection_summary(gold_rows: list[Any], predictions: dict[tuple[str, str, str], dict[str, Any]]) -> dict[str, Any]:
        strict_correct = 0
        valid_correct = 0
        valid_count = 0
        for gold_row in gold_rows:
            expected = bool(normalize_evidence(gold_row.missing_information))
            prediction = predictions.get(gold_row.key())
            if prediction is None or prediction.get("status") != "ok":
                continue
            valid_count += 1
            actual = prediction.get("missing_information_detected")
            correct = isinstance(actual, bool) and actual == expected
            strict_correct += int(correct)
            valid_correct += int(correct)
        total = len(gold_rows)
        return {
            "numerator": strict_correct,
            "denominator": total,
            "value": strict_correct / total if total else 0.0,
            "valid_output_numerator": valid_correct,
            "valid_output_denominator": valid_count,
            "valid_output_value": valid_correct / valid_count if valid_count else 0.0,
            "failure_treatment": "missing or failed batches counted wrong",
        }

    def postprocess_report(self, report: dict[str, Any], *, gold_path: Path, predictions_path: Path) -> dict[str, Any]:
        gold = load_gold(gold_path)
        predictions = self._load_predictions(predictions_path)
        gold_by_key = {row.key(): row for row in gold.records}

        for record in report.get("records", []):
            key_payload = record["key"]
            key = (str(key_payload["case_id"]), str(key_payload["variant_id"]), str(key_payload["question_id"]))
            gold_row = gold_by_key[key]
            prediction = predictions.get(key, {})
            expected = bool(normalize_evidence(gold_row.missing_information))
            actual = prediction.get("missing_information_detected")
            record["missing_information_correct"] = None
            record["missing_information_detection_expected"] = expected
            record["missing_information_detected"] = actual if isinstance(actual, bool) else None
            record["missing_information_detection_correct"] = isinstance(actual, bool) and actual == expected

        summary = self._detection_summary(list(gold.records), predictions)
        report["overall"]["missing_information_accuracy"] = None
        report["overall"]["missing_information_detection_accuracy"] = summary["value"]
        report["overall"]["valid_output_missing_information_detection_accuracy"] = summary["valid_output_value"]
        report["overall"]["missing_information_detection_numerator"] = summary["numerator"]
        report["overall"]["missing_information_detection_denominator"] = summary["denominator"]

        grouped_by_type: dict[str, list[Any]] = defaultdict(list)
        grouped_by_variant: dict[str, list[Any]] = defaultdict(list)
        for row in gold.records:
            grouped_by_type[row.answer_type].append(row)
            grouped_by_variant[row.variant_id].append(row)
        for answer_type, rows in grouped_by_type.items():
            if answer_type in report.get("by_answer_type", {}):
                type_summary = self._detection_summary(rows, predictions)
                report["by_answer_type"][answer_type]["missing_information_accuracy"] = None
                report["by_answer_type"][answer_type]["missing_information_detection_accuracy"] = type_summary["value"]
        for variant_id, rows in grouped_by_variant.items():
            if variant_id in report.get("variant_metrics", {}):
                variant_summary = self._detection_summary(rows, predictions)
                report["variant_metrics"][variant_id]["missing_information_accuracy"] = None
                report["variant_metrics"][variant_id]["missing_information_detection_accuracy"] = variant_summary["value"]

        report.setdefault("metric_contracts", {})["missing_information"] = {
            "protocol": self.name,
            "available": "detection_only",
            "primary_metric": "missing_information_detection_accuracy",
            "unavailable_metric": "exact missing-information set accuracy",
            "reason": "the compact response schema returns only boolean field m",
        }
        return report

    def postprocess_csv(self, csv_path: Path, report: dict[str, Any]) -> None:
        if not csv_path.exists():
            return
        records = {
            (row["key"]["case_id"], row["key"]["variant_id"], row["key"]["question_id"]): row
            for row in report.get("records", [])
        }
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys()) if rows else []
        if "missing_information_detection_correct" not in fieldnames:
            fieldnames.append("missing_information_detection_correct")
        for row in rows:
            key = (row["case_id"], row["variant_id"], row["question_id"])
            record = records.get(key, {})
            row["missing_information_correct"] = ""
            row["missing_information_detection_correct"] = record.get("missing_information_detection_correct", "")
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
