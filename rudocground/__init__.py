"""RuDocGround evaluation toolkit."""

from .metrics import evaluate
from .models import GoldRecord, PredictionRecord

__all__ = ["evaluate", "GoldRecord", "PredictionRecord"]
