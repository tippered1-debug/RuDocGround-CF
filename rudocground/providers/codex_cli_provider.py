from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
import json
import os
import shutil
import subprocess
import tempfile

from ..models import ModelPrediction, PromptTask, coerce_output_answer


CODEx_BASE_INSTRUCTION = (
    "Ты проходишь закрытый тест. Используй только документы и вопрос внутри переданного prompt. "
    "Не обращайся к интернету, локальным файлам, предыдущим заданиям или внешним инструментам. "
    "Верни только JSON по заданной схеме."
)


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _npm_global_prefix() -> str | None:
    npm_path = shutil.which("npm")
    if not npm_path:
        return None
    try:
        completed = subprocess.run(
            [npm_path, "prefix", "-g"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    prefix = (completed.stdout or completed.stderr or "").strip()
    return prefix or None


def _resolve_codex_binary(explicit_binary: str | None = None) -> tuple[str | None, list[str]]:
    candidates: list[str] = []
    if explicit_binary:
        candidates.append(explicit_binary)
    env_binary = os.environ.get("RUDOCGROUND_CODEX_BINARY")
    if env_binary:
        candidates.append(env_binary)
    which_binary = shutil.which("codex")
    if which_binary:
        candidates.append(which_binary)
    candidates.extend(
        [
            "/opt/homebrew/bin/codex",
            "/usr/local/bin/codex",
        ]
    )
    npm_prefix = _npm_global_prefix()
    if npm_prefix:
        candidates.append(str(Path(npm_prefix) / "bin" / "codex"))

    checked: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(Path(candidate).expanduser().resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        checked.append(resolved)
        if _is_executable_file(Path(resolved)):
            return resolved, checked
    return None, checked


def _codex_not_found_error(checked_paths: list[str]) -> RuntimeError:
    path_env = os.environ.get("PATH", "")
    message = (
        "codex binary is required for CodexCliProvider\n"
        f"PATH={path_env}\n"
        f"checked_paths={checked_paths}\n"
        "Set --codex-binary or RUDOCGROUND_CODEX_BINARY to point to the Codex CLI executable."
    )
    return RuntimeError(message)


def _codex_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "answer": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "number"},
                    {"type": "boolean"},
                    {"type": "null"},
                ]
            },
            "decision": {"anyOf": [{"type": "string"}, {"type": "null"}]},
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


def _schema_path(schema: dict[str, Any], temp_dir: Path) -> Path:
    path = temp_dir / "schema.json"
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _parse_json_output(text: str) -> Any:
    if not text.strip():
        return None
    return json.loads(text)


def _parse_jsonl_events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _has_tool_use(events: list[dict[str, Any]]) -> bool:
    toolish = {
        "tool",
        "tool.started",
        "tool.completed",
        "tool_call",
        "tool_result",
        "web_search",
        "file_search",
        "read_file",
        "write_file",
    }
    for event in events:
        text = json.dumps(event, ensure_ascii=False).lower()
        if any(marker in text for marker in toolish):
            return True
    return False


def _event_tools(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for event in events:
        text = json.dumps(event, ensure_ascii=False).lower()
        if any(marker in text for marker in ("web_search", "file", "tool")):
            tools.append(event)
    return tools


def _allowed_decision_labels(task: PromptTask) -> list[str]:
    schema = task.response_schema or {}
    labels = schema.get("allowed_decision_labels")
    if isinstance(labels, list):
        return [str(label) for label in labels if str(label).strip()]
    decision = schema.get("decision")
    if isinstance(decision, str) and decision.strip():
        return [decision.strip()]
    return []


def _allowed_code_values(task: PromptTask) -> list[str]:
    schema = task.response_schema or {}
    values = schema.get("allowed_code_values")
    if isinstance(values, list):
        return [str(value) for value in values if str(value).strip()]
    return []


def _allowed_answer_values(task: PromptTask) -> list[str]:
    schema = task.response_schema or {}
    values = schema.get("allowed_answer_values")
    if isinstance(values, list):
        return [str(value) for value in values if str(value).strip()]
    return []


def _answer_schema(task: PromptTask) -> dict[str, Any]:
    answer_type = task.answer_type or (task.response_schema or {}).get("answer_type")
    allowed_answers = _allowed_answer_values(task)
    if allowed_answers:
        return {
            "type": "string",
            "enum": allowed_answers,
        }
    if answer_type == "code_set":
        allowed_codes = _allowed_code_values(task)
        if allowed_codes:
            return {
                "type": "object",
                "additionalProperties": False,
                "properties": {code: {"type": "boolean"} for code in allowed_codes},
                "required": allowed_codes,
            }
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
            "required": [],
        }
    if answer_type == "identifier":
        return {"type": "string"}
    return {
        "anyOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "boolean"},
            {"type": "null"},
        ]
    }


def _decision_schema(task: PromptTask) -> dict[str, Any]:
    if task.decision_required:
        labels = _allowed_decision_labels(task)
        if labels:
            return {"type": "string", "enum": labels}
        return {"type": "string"}
    return {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _codex_schema(task: PromptTask) -> dict[str, Any]:
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


def _base_command(binary: str, model: str, schema_file: Path, response_file: Path) -> list[str]:
    cmd = [
        binary,
        "--ask-for-approval",
        "never",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--ignore-user-config",
        "--ignore-rules",
        "--json",
        "--color",
        "never",
        "--output-schema",
        str(schema_file),
        "-o",
        str(response_file),
    ]
    if model and model != "codex-default":
        cmd.extend(["--model", model])
    return cmd


def _codex_version(explicit_binary: str | None = None) -> str | None:
    binary, _checked = _resolve_codex_binary(explicit_binary)
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [binary, "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    version = (completed.stdout or completed.stderr or "").strip()
    return version or None


def _doctor_report(explicit_binary: str | None = None) -> dict[str, Any]:
    binary, checked = _resolve_codex_binary(explicit_binary)
    if binary is None:
        return {"available": False, "auth": False, "doctor": None, "resolved_binary_path": None, "checked_binary_paths": checked}
    try:
        completed = subprocess.run(
            [binary, "doctor", "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        return {"available": True, "auth": False, "doctor": None, "error": str(exc)}
    try:
        report = json.loads(completed.stdout)
    except Exception:
        report = None
    auth_ok = False
    if isinstance(report, dict):
        checks = report.get("checks", {})
        auth = checks.get("auth.credentials", {})
        auth_ok = auth.get("status") == "ok"
    return {
        "available": True,
        "auth": auth_ok,
        "doctor": report,
        "resolved_binary_path": binary,
        "checked_binary_paths": checked,
    }


def _structured_smoke_prompt() -> str:
    return (
        f"{CODEx_BASE_INSTRUCTION}\n\n"
        "Return a valid JSON object with answer 1 and empty arrays for evidence, evidence_details, and missing_information."
    )


@dataclass
class CodexCliProvider:
    model: str
    codex_binary: str | None = None
    client_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None
    tempdir_factory: Callable[[], tempfile.TemporaryDirectory[str]] | None = None
    codex_version_override: str | None = None
    resolved_binary_path: str | None = None
    checked_binary_paths: list[str] | None = None

    def __post_init__(self) -> None:
        resolved, checked = _resolve_codex_binary(self.codex_binary)
        self.resolved_binary_path = resolved
        self.checked_binary_paths = checked
        if resolved is None:
            raise _codex_not_found_error(checked)

    def _run_subprocess(self, cmd: list[str], *, cwd: str, prompt: str) -> subprocess.CompletedProcess[str]:
        runner = self.client_runner or subprocess.run
        return runner(
            cmd,
            input=prompt,
            text=True,
            capture_output=True,
            cwd=cwd,
        )

    def _make_tempdir(self) -> tempfile.TemporaryDirectory[str]:
        factory = self.tempdir_factory or tempfile.TemporaryDirectory
        return factory()

    def _binary(self) -> str:
        if self.resolved_binary_path is None:
            raise _codex_not_found_error(self.checked_binary_paths or [])
        return self.resolved_binary_path

    def _build_prompt(self, task: PromptTask) -> str:
        parts = [CODEx_BASE_INSTRUCTION]
        if task.system_prompt:
            parts.append(task.system_prompt)
        parts.append(task.prompt)
        return "\n\n".join(parts)

    def _parse_result(self, task: PromptTask, response_payload: Any, *, latency_ms: int, stdout: str, stderr: str, events: list[dict[str, Any]], returncode: int) -> ModelPrediction:
        tool_use_detected = _has_tool_use(events)
        evaluation_contaminated = tool_use_detected
        tool_events = _event_tools(events)
        raw_response = {
            "codex_cli_version": self.codex_version_override or _codex_version(),
            "stdout": stdout,
            "stderr": stderr,
            "events": events,
            "tool_events": tool_events,
            "tool_use_detected": tool_use_detected,
            "evaluation_contaminated": evaluation_contaminated,
            "returncode": returncode,
            "response": response_payload,
        }
        if not isinstance(response_payload, dict):
            raise RuntimeError("Codex response JSON is not an object")
        answer = coerce_output_answer(task.answer_type, response_payload.get("answer"))
        return ModelPrediction(
            case_id=task.case_id,
            variant_id=task.variant_id,
            question_id=task.question_id,
            answer=answer,
            decision=response_payload.get("decision"),
            evidence=response_payload.get("evidence", []),
            evidence_details=response_payload.get("evidence_details", []),
            missing_information=response_payload.get("missing_information", []),
            explanation=response_payload.get("explanation", ""),
            model=self.model,
            provider="codex_cli",
            latency_ms=latency_ms,
            input_tokens=None,
            output_tokens=None,
            status="ok",
            error=None,
            raw_response=raw_response,
            codex_cli_version=self.codex_version_override or _codex_version(),
            tool_use_detected=tool_use_detected,
            evaluation_contaminated=evaluation_contaminated,
        )

    def generate(self, task: PromptTask) -> ModelPrediction:
        prompt = self._build_prompt(task)
        started = perf_counter()
        with self._make_tempdir() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            schema_file = _schema_path(_codex_schema(task), temp_dir)
            response_file = temp_dir / "response.json"
            cmd = _base_command(self._binary(), self.model, schema_file, response_file)
            completed = self._run_subprocess(cmd, cwd=str(temp_dir), prompt=prompt)
            latency_ms = int((perf_counter() - started) * 1000)
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            events = _parse_jsonl_events(stdout)
            if completed.returncode != 0:
                raise RuntimeError(f"codex exec failed with exit code {completed.returncode}: {stderr.strip() or stdout.strip()}")
            if not response_file.exists():
                raise RuntimeError("codex exec completed without writing response file")
            response_payload = _parse_json_output(response_file.read_text(encoding="utf-8"))
            if response_payload is None:
                raise RuntimeError("codex exec returned empty JSON response")
            return self._parse_result(
                task,
                response_payload,
                latency_ms=latency_ms,
                stdout=stdout,
                stderr=stderr,
                events=events,
                returncode=completed.returncode,
            )


def codex_diagnostics(codex_binary: str | None = None) -> dict[str, Any]:
    report = _doctor_report(codex_binary)
    version = _codex_version(codex_binary)
    smoke_ok = False
    smoke_error: str | None = None
    if report.get("available"):
        try:
            provider = CodexCliProvider(model="codex-default", codex_binary=codex_binary, codex_version_override=version)
            task = PromptTask(
                case_id="smoke",
                variant_id="A",
                question_id="Q1",
                prompt=_structured_smoke_prompt(),
                system_prompt=None,
                response_schema={
                    "case_id": "smoke",
                    "variant_id": "A",
                    "question_id": "Q1",
                    "answer": None,
                    "decision": None,
                    "evidence": [],
                    "evidence_details": [],
                    "missing_information": [],
                    "explanation": "",
                },
            )
            prediction = provider.generate(task)
            smoke_ok = prediction.status == "ok"
        except Exception as exc:
            smoke_error = str(exc)
    return {
        "codex_found": report.get("available", False),
        "codex_version": version,
        "authorized": report.get("auth", False),
        "exec_available": report.get("available", False),
        "resolved_binary_path": report.get("resolved_binary_path"),
        "checked_binary_paths": report.get("checked_binary_paths", []),
        "smoke_test_ok": smoke_ok,
        "smoke_test_error": smoke_error,
        "doctor": report.get("doctor"),
    }
