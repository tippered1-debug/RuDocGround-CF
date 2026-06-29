from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any
import os
import random
import re
import sys
import time

from ..models import ModelPrediction, PredictionBody, PromptTask


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
BASE_BACKOFF_SECONDS = (15, 30, 60, 120)


def _parse_retry_delay_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        match = re.fullmatch(r"(?P<seconds>\d+(?:\.\d+)?)s?", text)
        if match:
            return float(match.group("seconds"))
        return None
    if isinstance(value, dict):
        if "seconds" in value or "nanos" in value:
            seconds = float(value.get("seconds") or 0)
            nanos = float(value.get("nanos") or 0)
            return seconds + nanos / 1_000_000_000
    return None


def _find_retry_delay_seconds(value: Any) -> float | None:
    if value is None:
        return None
    parsed = _parse_retry_delay_seconds(value)
    if parsed is not None:
        return parsed
    if isinstance(value, dict):
        for key in ("retryDelay", "retry_delay"):
            if key in value:
                parsed = _find_retry_delay_seconds(value[key])
                if parsed is not None:
                    return parsed
        for item in value.values():
            parsed = _find_retry_delay_seconds(item)
            if parsed is not None:
                return parsed
    elif isinstance(value, list):
        for item in value:
            parsed = _find_retry_delay_seconds(item)
            if parsed is not None:
                return parsed
    return None


def _extract_retry_delay_seconds(exc: Exception) -> float | None:
    for attr in ("details", "body"):
        parsed = _find_retry_delay_seconds(getattr(exc, attr, None))
        if parsed is not None:
            return parsed
    response = getattr(exc, "response", None)
    if response is not None:
        for attr in ("json", "model_dump"):
            method = getattr(response, attr, None)
            if callable(method):
                try:
                    parsed = _find_retry_delay_seconds(method())
                except Exception:
                    parsed = None
                if parsed is not None:
                    return parsed
        parsed = _find_retry_delay_seconds(getattr(response, "text", None))
        if parsed is not None:
            return parsed
    return None


def _retryable_reason(exc: Exception) -> str | None:
    try:
        from google.genai._interactions import _exceptions as gemini_errors
    except Exception:  # pragma: no cover - import side effect varies by env
        gemini_errors = None

    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    status = str(getattr(exc, "status", "") or getattr(exc, "message", "") or "").upper()
    message = str(exc).lower()

    if gemini_errors is not None and isinstance(exc, (gemini_errors.BadRequestError, gemini_errors.AuthenticationError, gemini_errors.PermissionDeniedError, gemini_errors.NotFoundError, gemini_errors.ConflictError, gemini_errors.UnprocessableEntityError)):
        return None
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return "rate_limit"
    if code in {500, 502, 503, 504} or (gemini_errors is not None and isinstance(exc, gemini_errors.InternalServerError)):
        return "server_error"
    retryable_markers = (
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "service unavailable",
        "network",
    )
    if any(marker in message for marker in retryable_markers):
        return "transient_network"
    try:
        import httpx
        import requests
    except Exception:  # pragma: no cover - optional deps always available in env
        httpx = None
        requests = None
    if httpx is not None and isinstance(exc, (httpx.RequestError, httpx.TimeoutException)):
        return "transient_network"
    if requests is not None and isinstance(exc, requests.exceptions.RequestException):
        return "transient_network"
    return None


def _backoff_seconds(attempt: int) -> float:
    if attempt <= 0:
        return BASE_BACKOFF_SECONDS[0]
    index = min(attempt - 1, len(BASE_BACKOFF_SECONDS) - 1)
    return float(BASE_BACKOFF_SECONDS[index])


def _extract_raw_response(response: Any) -> Any:
    if hasattr(response, "model_dump"):
        try:
            return response.model_dump(mode="json")
        except TypeError:
            return response.model_dump()
    if isinstance(response, dict):
        return response
    return response


def _extract_usage(response: Any) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage_metadata", None) or getattr(response, "usageMetadata", None)
    if usage is None:
        return None, None
    input_tokens = getattr(usage, "prompt_token_count", None)
    output_tokens = getattr(usage, "candidates_token_count", None)
    if output_tokens is None:
        output_tokens = getattr(usage, "total_token_count", None)
    return input_tokens, output_tokens


def _strip_additional_properties(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"additionalProperties", "additional_properties"}:
                continue
            cleaned[key] = _strip_additional_properties(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_additional_properties(item) for item in value]
    return value


@dataclass
class GeminiProvider:
    model: str
    max_retries: int = 3
    request_delay: float = 0.0
    min_request_interval: float = 0.0
    client: Any | None = None
    _last_request_started_at: float | None = None

    def __post_init__(self) -> None:
        if self.client is not None:
            return
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is required")
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - import error depends on env
            raise RuntimeError("google-genai package is required for GeminiProvider") from exc
        self.client = genai.Client(api_key=api_key)

    def _sleep_before_request(self) -> None:
        if self.request_delay > 0:
            time.sleep(self.request_delay)

    def _pace_requests(self) -> None:
        if self.min_request_interval <= 0 or self._last_request_started_at is None:
            return
        elapsed = time.monotonic() - self._last_request_started_at
        remaining = self.min_request_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _response_config(self) -> Any:
        from google.genai import types

        kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_json_schema": _strip_additional_properties(PredictionBody.model_json_schema()),
        }
        try:
            kwargs["temperature"] = 0
        except Exception:
            pass
        return types.GenerateContentConfig(**kwargs)

    def _build_contents(self, task: PromptTask) -> list[str]:
        if task.system_prompt:
            return [task.system_prompt, task.prompt]
        return [task.prompt]

    def _parse_prediction(self, response: Any, task: PromptTask, latency_ms: int) -> ModelPrediction:
        parsed = getattr(response, "parsed", None)
        if parsed is None and getattr(response, "candidates", None):
            candidate = response.candidates[0]
            parts = getattr(getattr(candidate, "content", None), "parts", [])
            for part in parts:
                parsed = getattr(part, "parsed", None)
                if parsed is not None:
                    break
        if parsed is None:
            raise RuntimeError("Gemini response did not include parsed structured output")
        payload = parsed.model_dump(mode="json") if hasattr(parsed, "model_dump") else dict(parsed)
        input_tokens, output_tokens = _extract_usage(response)
        return ModelPrediction(
            case_id=task.case_id,
            variant_id=task.variant_id,
            question_id=task.question_id,
            answer=payload.get("answer"),
            decision=payload.get("decision", ""),
            evidence=payload.get("evidence", []),
            evidence_details=payload.get("evidence_details", []),
            missing_information=payload.get("missing_information", []),
            explanation=payload.get("explanation", ""),
            model=self.model,
            provider="gemini",
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status="ok",
            error=None,
            raw_response=_extract_raw_response(response),
        )

    def generate(self, task: PromptTask) -> ModelPrediction:
        attempt_limit = max(1, min(int(self.max_retries or 1), 5))
        last_exc: Exception | None = None
        config = self._response_config()
        for attempt in range(1, attempt_limit + 1):
            try:
                self._pace_requests()
                self._sleep_before_request()
                self._last_request_started_at = time.monotonic()
                started = perf_counter()
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=self._build_contents(task),
                    config=config,
                )
                latency_ms = int((perf_counter() - started) * 1000)
                return self._parse_prediction(response, task, latency_ms)
            except Exception as exc:
                last_exc = exc
                reason = _retryable_reason(exc)
                if reason is None or attempt >= attempt_limit:
                    break
                retry_delay = _extract_retry_delay_seconds(exc) if reason == "rate_limit" else None
                if retry_delay is None:
                    retry_delay = _backoff_seconds(attempt)
                wait_seconds = retry_delay + random.uniform(0.05, min(1.0, max(retry_delay * 0.1, 0.1)))
                print(
                    f"Gemini retry attempt={attempt} reason={reason} wait={wait_seconds:.2f}s",
                    file=sys.stderr,
                )
                time.sleep(wait_seconds)
        assert last_exc is not None
        raise last_exc
