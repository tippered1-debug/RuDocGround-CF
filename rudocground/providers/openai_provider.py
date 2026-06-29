from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any
import os
import random
import time

from ..models import ModelPrediction, PredictionBody, PromptTask


@dataclass
class OpenAIProvider:
    model: str
    max_retries: int = 3
    request_delay: float = 0.0

    def __post_init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is required")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - import error depends on env
            raise RuntimeError("openai package is required for OpenAIProvider") from exc
        self._client = OpenAI()
        self._supports_temperature = True
        self._disable_temperature_after_failure = False

    def _sleep_before_request(self) -> None:
        if self.request_delay > 0:
            time.sleep(self.request_delay)

    def _should_retry(self, exc: Exception) -> bool:
        try:
            from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
        except ImportError:  # pragma: no cover
            return False
        return isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError))

    def _temperature_kwargs(self) -> dict[str, Any]:
        if self._disable_temperature_after_failure:
            return {}
        return {"temperature": 0}

    def _build_instructions(self, task: PromptTask) -> str | None:
        pieces = [piece for piece in [task.system_prompt, task.prompt] if piece]
        if not pieces:
            return None
        if task.system_prompt:
            return task.system_prompt
        return None

    def _build_input(self, task: PromptTask) -> str:
        return task.prompt

    def _parse_response(self, response: Any, task: PromptTask, latency_ms: int) -> ModelPrediction:
        parsed = None
        raw_response = None
        if hasattr(response, "output"):
            raw_response = response.model_dump(mode="json") if hasattr(response, "model_dump") else response
            for message in response.output:
                if getattr(message, "type", None) != "message":
                    continue
                for item in getattr(message, "content", []):
                    if getattr(item, "type", None) == "output_text" and getattr(item, "parsed", None) is not None:
                        parsed = item.parsed
                        break
                if parsed is not None:
                    break
        if parsed is None:
            raise RuntimeError("structured prediction was not returned by the model")
        payload = parsed.model_dump() if hasattr(parsed, "model_dump") else dict(parsed)
        return ModelPrediction(
            case_id=task.case_id,
            variant_id=task.variant_id,
            question_id=task.question_id,
            answer=payload["answer"],
            decision=payload["decision"],
            evidence=payload.get("evidence", []),
            evidence_details=payload.get("evidence_details", []),
            missing_information=payload.get("missing_information", []),
            explanation=payload.get("explanation", ""),
            model=self.model,
            provider="openai",
            latency_ms=latency_ms,
            input_tokens=getattr(getattr(response, "usage", None), "input_tokens", None),
            output_tokens=getattr(getattr(response, "usage", None), "output_tokens", None),
            status="ok",
            error=None,
            raw_response=raw_response,
        )

    def generate(self, task: PromptTask) -> ModelPrediction:
        import openai

        self._sleep_before_request()
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                started = perf_counter()
                response = self._client.responses.parse(
                    model=self.model,
                    input=self._build_input(task),
                    instructions=self._build_instructions(task),
                    text_format=PredictionBody,
                    **self._temperature_kwargs(),
                )
                latency_ms = int((perf_counter() - started) * 1000)
                return self._parse_response(response, task, latency_ms)
            except openai.BadRequestError as exc:
                message = str(exc).lower()
                if "temperature" in message and not self._disable_temperature_after_failure:
                    self._disable_temperature_after_failure = True
                    last_exc = exc
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_retries or not self._should_retry(exc):
                    break
                backoff = min(2 ** (attempt - 1), 8) + random.random() * 0.1
                time.sleep(backoff)
        assert last_exc is not None
        raise last_exc
