from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from .models import GoldRecord, LoadedDataset, PredictionRecord


class DataFormatError(ValueError):
    pass


T = TypeVar("T", GoldRecord, PredictionRecord)


@dataclass
class LoadIssue:
    lineno: int | None
    kind: str
    message: str


@dataclass
class PredictionLoadReport:
    dataset: LoadedDataset
    issues: list[LoadIssue] = field(default_factory=list)


def _load_jsonl(path: Path, model: type[T]) -> LoadedDataset:
    if not path.exists():
        raise FileNotFoundError(path)
    records: list[T] = []
    by_key: dict[tuple[str, str, str], T] = {}
    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = model.model_validate_json(line)
            except ValidationError as exc:
                raise DataFormatError(f"{path}:{lineno}: {exc}") from exc
            key = record.key()
            if key in by_key:
                raise DataFormatError(f"{path}:{lineno}: duplicate key {key}")
            by_key[key] = record
            records.append(record)
    return LoadedDataset(records=records, by_key=by_key)


def load_gold(path: str | Path) -> LoadedDataset:
    return _load_jsonl(Path(path), GoldRecord)


def load_predictions(path: str | Path) -> LoadedDataset:
    return _load_jsonl(Path(path), PredictionRecord)


def load_predictions_with_issues(path: str | Path) -> PredictionLoadReport:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    records: list[PredictionRecord] = []
    by_key: dict[tuple[str, str, str], PredictionRecord] = {}
    issues: list[LoadIssue] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = PredictionRecord.model_validate_json(line)
            except ValidationError as exc:
                issues.append(LoadIssue(lineno=lineno, kind="invalid_row", message=str(exc)))
                continue
            key = record.key()
            if key in by_key:
                issues.append(LoadIssue(lineno=lineno, kind="duplicate_key", message=f"duplicate key {key}"))
                continue
            by_key[key] = record
            records.append(record)
    return PredictionLoadReport(dataset=LoadedDataset(records=records, by_key=by_key), issues=issues)


def ensure_all_gold_present(gold: LoadedDataset, predictions: LoadedDataset) -> None:
    missing = [key for key in gold.by_key if key not in predictions.by_key]
    if missing:
        preview = ", ".join(map(str, missing[:5]))
        suffix = "" if len(missing) <= 5 else f" (+{len(missing) - 5} more)"
        raise DataFormatError(f"missing predictions for {preview}{suffix}")
