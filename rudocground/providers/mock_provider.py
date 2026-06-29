from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..models import ModelPrediction, PromptTask


MockResponse = ModelPrediction | dict[str, Any] | Exception | Callable[[PromptTask], ModelPrediction | dict[str, Any]]


@dataclass
class MockProvider:
    responses: dict[tuple[str, str, str], MockResponse] = field(default_factory=dict)
    default_response: MockResponse | None = None
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    def generate(self, task: PromptTask) -> ModelPrediction:
        key = task.key()
        self.calls.append(key)
        response = self.responses.get(key, self.default_response)
        if response is None:
            raise KeyError(f"no mock response configured for {key}")
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(task)
        if isinstance(response, ModelPrediction):
            return response
        payload = dict(response)
        payload.setdefault("case_id", task.case_id)
        payload.setdefault("variant_id", task.variant_id)
        payload.setdefault("question_id", task.question_id)
        return ModelPrediction.model_validate(payload)
