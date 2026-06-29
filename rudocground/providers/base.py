from __future__ import annotations

from typing import Protocol

from ..models import ModelPrediction, PromptTask


class ModelProvider(Protocol):
    def generate(self, task: PromptTask) -> ModelPrediction:
        raise NotImplementedError
