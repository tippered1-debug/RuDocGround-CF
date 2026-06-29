from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
import json
import os
import random
import subprocess
import urllib.error
import urllib.request

from ..models import ModelPrediction, PromptTask, coerce_output_answer
from .codex_cli_provider import _codex_schema


OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434/api/chat"


def _is_retryable_http_status(status: int | None) -> bool:
    return status in {408, 409, 425, 429, 500, 502, 503, 504}


def _build_answer_schema(task: PromptTask) -> dict[str, Any]:
    answer_type = task.answer_type or (task.response_schema or {}).get("answer_type")
    schema = _codex_schema(task)
    if answer_type == "boolean":
        schema["properties"]["answer"] = {"type": "boolean"}
        return schema
    if answer_type == "integer":
        schema["properties"]["answer"] = {"type": "integer"}
        return schema
    if answer_type == "money":
        schema["properties"]["answer"] = {"type": "number"}
        return schema
    if answer_type == "date" or answer_type == "datetime" or answer_type == "identifier":
        schema["properties"]["answer"] = {"type": "string"}
        return schema
    if answer_type != "code_set":
        allowed_answers = (task.response_schema or {}).get("allowed_answer_values")
        if isinstance(allowed_answers, list) and allowed_answers:
            schema["properties"]["answer"] = {
                "type": "string",
                "enum": [str(value) for value in allowed_answers if str(value).strip()],
            }
        else:
            schema["properties"]["answer"] = {"type": "string"}
        return schema

    code_values = (task.response_schema or {}).get("allowed_code_values")
    if not isinstance(code_values, list):
        code_values = []

    universe: list[str] = []
    seen: set[str] = set()
    for raw_value in code_values:
        value = str(raw_value).strip()
        if not value:
            continue
        parts = [part.strip() for part in value.split("|") if part.strip()]
        if not parts:
            parts = [value]
        for part in parts:
            if part not in seen:
                seen.add(part)
                universe.append(part)

    answer_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {code: {"type": "boolean"} for code in universe},
        "required": universe,
    }
    schema["properties"]["answer"] = answer_schema
    return schema


def _parse_json_content(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return json.loads(text)
    return value


def _ollama_list() -> list[str]:
    completed = subprocess.run(
        ["ollama", "list"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "ollama list failed").strip())
    models: list[str] = []
    for line in (completed.stdout or "").splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def _extract_usage(response: dict[str, Any]) -> tuple[int | None, int | None]:
    prompt_eval = response.get("prompt_eval_count")
    eval_count = response.get("eval_count")
    return (
        int(prompt_eval) if isinstance(prompt_eval, int) else None,
        int(eval_count) if isinstance(eval_count, int) else None,
    )


def _response_content(response: dict[str, Any]) -> Any:
    message = response.get("message")
    if isinstance(message, dict):
        if "parsed" in message and message["parsed"] is not None:
            return message["parsed"]
        return message.get("content")
    return None


def _build_raw_response(
    *,
    request_body: dict[str, Any],
    response_body: dict[str, Any],
    parsed_payload: Any,
    latency_ms: int,
    status_code: int | None = None,
) -> dict[str, Any]:
    prompt_eval_count, eval_count = _extract_usage(response_body)
    return {
        "provider": "ollama",
        "model": request_body.get("model"),
        "request": request_body,
        "response": response_body,
        "parsed_response": parsed_payload,
        "latency_ms": latency_ms,
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "status_code": status_code,
    }


@dataclass
class OllamaChatResult:
    request_body: dict[str, Any]
    response_body: dict[str, Any]
    parsed_payload: Any
    latency_ms: int
    prompt_eval_count: int | None
    eval_count: int | None
    raw_response: dict[str, Any]


@dataclass
class OllamaProvider:
    model: str
    base_url: str = OLLAMA_DEFAULT_URL
    temperature: float = 0.0
    seed: int = 42
    stream: bool = False
    think: bool = False
    keep_alive: str = "30m"
    num_ctx: int = 16384
    num_predict: int = 1024
    timeout: float = 1800.0
    max_retries: int = 3
    opener: Callable[[urllib.request.Request, float], Any] | None = None

    def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        opener = self.opener or urllib.request.urlopen
        with opener(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("ollama response is not an object")
        return parsed

    def _chat(self, *, system_prompt: str | None, user_prompt: str, response_schema: dict[str, Any]) -> OllamaChatResult:
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": [],
            "stream": self.stream,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature,
                "seed": self.seed,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
            "format": response_schema,
        }
        if system_prompt:
            request_body["messages"].append({"role": "system", "content": system_prompt})
        request_body["messages"].append({"role": "user", "content": user_prompt})

        last_exc: Exception | None = None
        for attempt in range(1, max(1, self.max_retries) + 1):
            started = perf_counter()
            try:
                response_body = self._request(request_body)
                latency_ms = int((perf_counter() - started) * 1000)
                parsed_payload = _parse_json_content(_response_content(response_body))
                if parsed_payload is None:
                    raise RuntimeError("ollama response did not include structured content")
                if not isinstance(parsed_payload, dict):
                    raise RuntimeError("ollama structured content is not an object")
                prompt_eval_count, eval_count = _extract_usage(response_body)
                return OllamaChatResult(
                    request_body=request_body,
                    response_body=response_body,
                    parsed_payload=parsed_payload,
                    latency_ms=latency_ms,
                    prompt_eval_count=prompt_eval_count,
                    eval_count=eval_count,
                    raw_response=_build_raw_response(
                        request_body=request_body,
                        response_body=response_body,
                        parsed_payload=parsed_payload,
                        latency_ms=latency_ms,
                    ),
                )
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if not _is_retryable_http_status(exc.code) or attempt >= max(1, self.max_retries):
                    break
            except urllib.error.URLError as exc:
                last_exc = exc
                if attempt >= max(1, self.max_retries):
                    break
            except Exception as exc:
                last_exc = exc
                if attempt >= max(1, self.max_retries):
                    break
            delay = min(2 ** (attempt - 1), 8) + random.random() * 0.1
            import time

            time.sleep(delay)
        assert last_exc is not None
        raise last_exc

    def generate(self, task: PromptTask) -> ModelPrediction:
        result = self._chat(
            system_prompt=task.system_prompt,
            user_prompt=task.prompt,
            response_schema=_build_answer_schema(task),
        )
        payload = result.parsed_payload
        answer = coerce_output_answer(task.answer_type, payload.get("answer"))
        return ModelPrediction(
            case_id=task.case_id,
            variant_id=task.variant_id,
            question_id=task.question_id,
            answer=answer,
            decision=payload.get("decision"),
            evidence=payload.get("evidence", []),
            evidence_details=payload.get("evidence_details", []),
            missing_information=payload.get("missing_information", []),
            explanation=payload.get("explanation", ""),
            model=self.model,
            provider="ollama",
            latency_ms=result.latency_ms,
            input_tokens=result.prompt_eval_count,
            output_tokens=result.eval_count,
            status="ok",
            error=None,
            raw_response=result.raw_response,
            tool_use_detected=False,
            evaluation_contaminated=False,
        )

    def diagnostics(self, *, prompt: str | None = None) -> dict[str, Any]:
        models = _ollama_list()
        api_ok = False
        sample_ok = False
        sample_error: str | None = None
        response: dict[str, Any] | None = None
        if self.model in models:
            api_ok = True
            sample_prompt = prompt or "Скажи по-русски одним словом: да."
            try:
                result = self._chat(
                    system_prompt="Ответь только JSON.",
                    user_prompt=sample_prompt,
                    response_schema={
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                    },
                )
                response = result.response_body
                sample_ok = True
            except Exception as exc:
                sample_error = str(exc)
        return {
            "ollama_list": models,
            "model_present": self.model in models,
            "api_available": api_ok,
            "sample_ok": sample_ok,
            "sample_error": sample_error,
            "response": response,
            "base_url": self.base_url,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "seed": self.seed,
            "temperature": self.temperature,
            "think": self.think,
            "keep_alive": self.keep_alive,
        }
