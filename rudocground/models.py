from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any, Iterable

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


KEY_FIELDS = ("case_id", "variant_id", "question_id")
SUPPORTED_ANSWER_TYPES = {
    "money",
    "integer",
    "boolean",
    "threshold",
    "date",
    "date_range",
    "datetime",
    "code_set",
    "json",
    "categorical",
    "identifier",
    "status",
}


def _strip_string(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split()).strip()
    return str(value).strip()


def _normalize_structured_empty(value: Any) -> list[Any]:
    value = _coerce_jsonish(value)
    if value is None:
        return []
    if isinstance(value, dict) and not value:
        return []
    if isinstance(value, (list, tuple, set)) and not value:
        return []
    if isinstance(value, str):
        text = value.strip().lower()
        if not text or text in {"null", "none"}:
            return []
    return value if isinstance(value, list) else ([value] if value != {} else [])


def _coerce_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") or text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
    return value


def _flatten_items(value: Any) -> list[Any]:
    value = _coerce_jsonish(value)
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        if not value.strip():
            return []
        if "|" in value:
            return [part.strip() for part in value.split("|") if part.strip()]
        if "," in value:
            return [part.strip() for part in value.split(",") if part.strip()]
        return [value.strip()]
    return [value]


def _canonical_money(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError(f"invalid money value: {value!r}")
    if isinstance(value, (int, Decimal)):
        amount = Decimal(str(value))
        return str(amount.quantize(Decimal("1"))) if amount == amount.to_integral() else format(amount.normalize(), "f").rstrip("0").rstrip(".")
    if isinstance(value, float):
        amount = Decimal(str(value))
        return str(amount.quantize(Decimal("1"))) if amount == amount.to_integral() else format(amount.normalize(), "f").rstrip("0").rstrip(".")
    text = _normalize_text(value)
    if not text:
        raise ValueError("empty money value")
    text = re.sub(r"[\u0000-\u001f\u007f]", "", text)
    currency = r"(?:руб(?:\.|лей|ля)?|rur|rub|р\.?|₽|€|\$)"
    money_match = re.fullmatch(rf"(?P<num>[-+]?\d[\d\s]*(?:[.,]\d+)?)\s*(?:{currency})", text, re.IGNORECASE)
    if money_match:
        text = money_match.group("num")
    else:
        money_search = re.search(rf"(?P<num>[-+]?\d[\d\s]*(?:[.,]\d+)?)\s*(?:{currency})", text, re.IGNORECASE)
        if money_search:
            text = money_search.group("num")
        else:
            bare_numeric = re.fullmatch(r"[-+]?\d[\d\s]*(?:[.,]\d+)?", text)
            if bare_numeric is None:
                raise ValueError(f"invalid money value: {value!r}")
            text = bare_numeric.group(0)
    text = re.sub(r"[\u00a0\u202f\s]", "", text)
    if not text:
        raise ValueError("empty money value")
    sign = ""
    if text[0] in "+-":
        sign, text = text[0], text[1:]
    decimal_match = re.search(r"([.,])(\d{1,2})$", text)
    if decimal_match:
        integer_part = re.sub(r"[^0-9]", "", text[: decimal_match.start(1)])
        fractional_part = decimal_match.group(2)
        text = f"{sign}{integer_part}.{fractional_part}"
    else:
        text = f"{sign}{re.sub(r'[^0-9]', '', text)}"
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid money value: {value!r}") from exc
    if amount == amount.to_integral():
        return str(amount.quantize(Decimal("1")))
    normalized = format(amount.normalize(), "f")
    return normalized.rstrip("0").rstrip(".")


def _canonical_integer(value: Any) -> str:
    text = _normalize_text(value).replace(" ", "").replace(",", "")
    if not text:
        raise ValueError("empty integer value")
    try:
        return str(int(text))
    except ValueError as exc:
        raise ValueError(f"invalid integer value: {value!r}") from exc


def _canonical_boolean(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = _normalize_text(value).lower()
    truthy = {"true", "t", "1", "yes", "y", "да"}
    falsy = {"false", "f", "0", "no", "n", "нет"}
    if text in truthy:
        return "true"
    if text in falsy:
        return "false"
    raise ValueError(f"invalid boolean value: {value!r}")


_THRESHOLD_RE = re.compile(
    r"^(?P<op>>=|<=|>|<|=)?\s*(?P<value>[-+]?\d+(?:[.,]\d+)?)$"
)
_THRESHOLD_WORDS = {
    "не менее": ">=",
    "как минимум": ">=",
    "at least": ">=",
    "no less than": ">=",
    "not less than": ">=",
    "не более": "<=",
    "как максимум": "<=",
    "больше или равно": ">=",
    "меньше или равно": "<=",
    "свыше": ">",
    "превышает": ">",
    "больше": ">",
    "выше": ">",
    "меньше": "<",
    "ниже": "<",
    "more than": ">",
    "greater than": ">",
    "no more than": "<=",
    "not more than": "<=",
    "at most": "<=",
    "less than": "<",
}


def _canonical_threshold(value: Any) -> str:
    if isinstance(value, dict):
        op = str(value.get("op") or value.get("operator") or "").strip()
        raw = value.get("value")
        if not op or raw is None:
            raise ValueError(f"invalid threshold value: {value!r}")
        return f"{op}{_canonical_numberish(raw)}"
    text = _normalize_text(value).lower()
    text = text.replace(" ", "")
    for phrase, op in _THRESHOLD_WORDS.items():
        compact = phrase.replace(" ", "")
        if text.startswith(compact):
            rest = text[len(compact) :]
            return f"{op}{_canonical_numberish(rest)}"
    match = _THRESHOLD_RE.match(text)
    if not match:
        raise ValueError(f"invalid threshold value: {value!r}")
    op = match.group("op") or "="
    return f"{op}{_canonical_numberish(match.group('value'))}"


def _canonical_numberish(value: Any) -> str:
    text = _normalize_text(value).replace(" ", "").replace(",", ".")
    if not text:
        raise ValueError("empty numeric value")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid numeric value: {value!r}") from exc
    normalized = format(number.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _parse_date(value: Any) -> date:
    text = _normalize_text(value)
    dotted = re.fullmatch(r"(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})", text)
    if dotted:
        text = f"{dotted.group('year')}-{dotted.group('month')}-{dotted.group('day')}"
    russian = re.fullmatch(
        r"(?P<day>\d{1,2})\s+(?P<month>января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(?P<year>\d{4})(?:\s+г\.?)?",
        text.lower(),
    )
    if russian:
        month_map = {
            "января": "01",
            "февраля": "02",
            "марта": "03",
            "апреля": "04",
            "мая": "05",
            "июня": "06",
            "июля": "07",
            "августа": "08",
            "сентября": "09",
            "октября": "10",
            "ноября": "11",
            "декабря": "12",
        }
        text = f"{russian.group('year')}-{month_map[russian.group('month')]}-{int(russian.group('day')):02d}"
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid date value: {value!r}") from exc


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_json_value(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted(_normalize_json_value(item) for item in value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return _canonical_datetime(value)
    return value


def _canonical_json(value: Any) -> str:
    normalized = _normalize_json_value(value)
    try:
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError as exc:
        raise ValueError(f"invalid json value: {value!r}") from exc


_BOUNDARY_PUNCT_RE = re.compile(r"^[\s\.,;:!?\"'()\[\]{}]+|[\s\.,;:!?\"'()\[\]{}]+$")
_MONTH_NAME_TO_SLUG = {
    "января": "январь",
    "январь": "январь",
    "февраля": "февраль",
    "февраль": "февраль",
    "марта": "март",
    "март": "март",
    "апреля": "апрель",
    "апрель": "апрель",
    "мая": "май",
    "май": "май",
    "июня": "июнь",
    "июнь": "июнь",
    "июля": "июль",
    "июль": "июль",
    "августа": "август",
    "август": "август",
    "сентября": "сентябрь",
    "сентябрь": "сентябрь",
    "октября": "октябрь",
    "октябрь": "октябрь",
    "ноября": "ноябрь",
    "ноябрь": "ноябрь",
    "декабря": "декабрь",
    "декабрь": "декабрь",
}
_MONTH_YEAR_LABEL_RE = re.compile(
    rf"(?P<month>{'|'.join(sorted(_MONTH_NAME_TO_SLUG))})\s+(?P<year>\d{{4}})(?:\s+г\.?)?$",
    re.IGNORECASE,
)


def _strip_boundary_punctuation(value: str) -> str:
    return _BOUNDARY_PUNCT_RE.sub("", value)


def _canonical_identifier(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        raise ValueError("empty identifier value")
    text = _strip_boundary_punctuation(text)
    text = " ".join(text.split())
    if not text:
        raise ValueError("empty identifier value")
    return text


def _canonical_categorical(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        raise ValueError("empty categorical value")
    text = _strip_boundary_punctuation(text)
    text = " ".join(text.split())
    if not text:
        raise ValueError("empty categorical value")
    return text


def _canonical_date_range(value: Any) -> str:
    if isinstance(value, dict):
        start = value.get("start") or value.get("from")
        end = value.get("end") or value.get("to")
        if start is None or end is None:
            raise ValueError(f"invalid date_range value: {value!r}")
        return f"{_parse_date(start).isoformat()}/{_parse_date(end).isoformat()}"
    text = _normalize_text(value)
    if not text:
        raise ValueError("empty date_range value")
    separators = ["..", " to ", " - ", "/", "|"]
    for sep in separators:
        if sep in text:
            start_text, end_text = text.split(sep, 1)
            return f"{_parse_date(start_text).isoformat()}/{_parse_date(end_text).isoformat()}"
    if len(text) >= 21 and text.count("/") >= 1:
        parts = text.split("/")
        if len(parts) == 2:
            return f"{_parse_date(parts[0]).isoformat()}/{_parse_date(parts[1]).isoformat()}"
    raise ValueError(f"invalid date_range value: {value!r}")


_MONTH_PATTERN = r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
_ISO_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?", re.IGNORECASE)
_COMPACT_DATETIME_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}(?::\d{2})?")
_RUSSIAN_DATETIME_RE = re.compile(
    rf"(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH_PATTERN})\s+(?P<year>\d{{4}})(?:\s+г\.?)?(?:\s*(?:,|\s+в\s+)\s*(?P<hour>\d{{1,2}}):(?P<minute>\d{{2}})(?::(?P<second>\d{{2}}))?)?",
    re.IGNORECASE,
)
_RUSSIAN_DATETIME_SEARCH_RE = re.compile(
    rf"\d{{1,2}}\s+{_MONTH_PATTERN}\s+\d{{4}}(?:\s+г\.?)?\s+в\s+\d{{1,2}}:\d{{2}}(?::\d{{2}})?",
    re.IGNORECASE,
)


def _parse_russian_datetime(text: str) -> datetime | None:
    match = _RUSSIAN_DATETIME_RE.fullmatch(text.lower())
    if not match:
        return None
    month_map = {
        "января": "01",
        "февраля": "02",
        "марта": "03",
        "апреля": "04",
        "мая": "05",
        "июня": "06",
        "июля": "07",
        "августа": "08",
        "сентября": "09",
        "октября": "10",
        "ноября": "11",
        "декабря": "12",
    }
    date_text = f"{match.group('year')}-{month_map[match.group('month')]}-{int(match.group('day')):02d}"
    hour = match.group("hour")
    minute = match.group("minute")
    second = match.group("second")
    if hour is None or minute is None:
        return datetime.fromisoformat(f"{date_text}T00:00:00")
    time_text = f"{int(hour):02d}:{minute}"
    if second:
        time_text += f":{second}"
    return datetime.fromisoformat(f"{date_text}T{time_text}")


def _parse_compact_datetime(text: str) -> datetime | None:
    match = _COMPACT_DATETIME_RE.fullmatch(text)
    if not match:
        return None
    day, month, year = text[:2], text[3:5], text[6:10]
    remainder = text[10:].strip()
    if not remainder:
        return datetime.fromisoformat(f"{year}-{month}-{day}T00:00:00")
    if remainder.startswith("T"):
        candidate = f"{year}-{month}-{day}{remainder}"
    else:
        candidate = f"{year}-{month}-{day}T{remainder}"
    return datetime.fromisoformat(candidate)


def _canonical_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
            return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        return dt.isoformat()
    text = _normalize_text(value)
    if not text:
        raise ValueError("empty datetime value")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        dt = _parse_russian_datetime(text)
        if dt is None:
            dt = _parse_compact_datetime(text)
    if dt is None:
        raise ValueError(f"invalid datetime value: {value!r}")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
        return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return dt.isoformat()


def _canonical_status(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        raise ValueError("empty status value")
    lowered = text.lower()
    month_year_match = _MONTH_YEAR_LABEL_RE.fullmatch(lowered)
    if month_year_match:
        month = _MONTH_NAME_TO_SLUG[month_year_match.group('month')]
        return f"{month}_{month_year_match.group('year')}"
    compact = _strip_boundary_punctuation(text)
    compact = " ".join(compact.split())
    if not compact:
        raise ValueError("empty status value")
    return compact


def _canonical_code_set(value: Any) -> str:
    items = _flatten_items(value)
    normalized = []
    for item in items:
        if item is None:
            continue
        text = _normalize_text(item)
        if not text:
            continue
        if any(ch.isspace() for ch in text):
            raise ValueError(f"invalid code_set value: {value!r}")
        if not re.fullmatch(r"[A-Za-z0-9_:-]+", text):
            raise ValueError(f"invalid code_set value: {value!r}")
        normalized.append(text)
    unique = sorted(dict.fromkeys(item for item in normalized if item))
    if not unique:
        raise ValueError("empty code_set value")
    return "|".join(unique)


def normalize_answer_value(answer_type: str, value: Any) -> str:
    answer_type = _normalize_text(answer_type)
    if answer_type == "money":
        return _canonical_money(value)
    if answer_type == "integer":
        return _canonical_integer(value)
    if answer_type == "boolean":
        return _canonical_boolean(value)
    if answer_type == "threshold":
        return _canonical_threshold(value)
    if answer_type == "date":
        return _parse_date(value).isoformat()
    if answer_type == "date_range":
        return _canonical_date_range(value)
    if answer_type == "datetime":
        return _canonical_datetime(value)
    if answer_type == "code_set":
        return _canonical_code_set(value)
    if answer_type == "json":
        return _canonical_json(value)
    if answer_type == "categorical":
        return _canonical_categorical(value)
    if answer_type == "identifier":
        return _canonical_identifier(value)
    if answer_type == "status":
        return _canonical_status(value)
    raise ValueError(f"unsupported answer_type: {answer_type!r}")


def normalize_evidence(value: Any) -> tuple[str, ...]:
    items = []
    for item in _flatten_items(value):
        if item is None:
            continue
        text = _normalize_text(item)
        if text:
            items.append(text)
    seen = set()
    unique = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return tuple(unique)


def normalize_evidence_doc_ids(value: Any) -> tuple[str, ...]:
    items = []
    for item in _flatten_items(value):
        if item is None:
            continue
        if isinstance(item, dict):
            doc_id = item.get("doc_id") or item.get("document_id")
            if doc_id is not None:
                items.append(_normalize_text(doc_id))
            continue
        text = _normalize_text(item)
        if not text:
            continue
        if "#" in text:
            text = text.split("#", 1)[0]
        doc_id_match = re.search(r"doc[_-]?id\s*[:=]\s*([A-Za-z0-9_:-]+)", text, re.IGNORECASE)
        if doc_id_match:
            text = doc_id_match.group(1)
        items.append(text)
    seen = set()
    unique = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return tuple(unique)


class GoldRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: str
    variant_id: str
    question_id: str
    answer_type: str
    answer_normalized: Any
    decision: str
    decision_required: bool = True
    required_evidence: Any = Field(default_factory=list)
    supporting_evidence: Any = Field(default_factory=list)
    missing_information: Any = Field(default_factory=list)
    must_change_from_other_variant: bool = False

    @field_validator("case_id", "variant_id", "question_id", "answer_type", "decision")
    @classmethod
    def _strip_strings(cls, value: str) -> str:
        value = _normalize_text(value)
        if not value:
            raise ValueError("field cannot be empty")
        return value

    @field_validator("decision_required", mode="before")
    @classmethod
    def _coerce_decision_required(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
        return bool(value)

    @field_validator("must_change_from_other_variant", mode="before")
    @classmethod
    def _coerce_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
        return bool(value)

    @model_validator(mode="after")
    def _validate_answer_type(self) -> "GoldRecord":
        if self.answer_type not in SUPPORTED_ANSWER_TYPES:
            raise ValueError(f"unsupported answer_type: {self.answer_type!r}")
        normalize_answer_value(self.answer_type, self.answer_normalized)
        return self

    def key(self) -> tuple[str, str, str]:
        return self.case_id, self.variant_id, self.question_id


class PredictionRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: str
    variant_id: str
    question_id: str
    answer_type: str | None = None
    answer_normalized: Any = Field(validation_alias=AliasChoices("answer_normalized", "answer"))
    decision: str | None = None
    decision_required: bool = False
    required_evidence: Any = Field(default_factory=list)
    supporting_evidence: Any = Field(default_factory=list, validation_alias=AliasChoices("supporting_evidence", "evidence"))
    missing_information: Any = Field(default_factory=list)
    must_change_from_other_variant: bool = False

    @field_validator("case_id", "variant_id", "question_id", "answer_type")
    @classmethod
    def _strip_strings(cls, value: str) -> str:
        value = _normalize_text(value)
        if not value:
            raise ValueError("field cannot be empty")
        return value

    @field_validator("decision")
    @classmethod
    def _strip_decision(cls, value: Any) -> str | None:
        if value is None:
            return None
        value = _normalize_text(value)
        if not value:
            return None
        return value

    @field_validator("must_change_from_other_variant", mode="before")
    @classmethod
    def _coerce_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
        return bool(value)

    @field_validator("missing_information", mode="before")
    @classmethod
    def _normalize_missing_information(cls, value: Any) -> Any:
        return _normalize_structured_empty(value)

    @field_validator("supporting_evidence", mode="before")
    @classmethod
    def _normalize_supporting_evidence(cls, value: Any) -> Any:
        return _normalize_structured_empty(value)

    @field_validator("required_evidence", mode="before")
    @classmethod
    def _normalize_required_evidence(cls, value: Any) -> Any:
        return _normalize_structured_empty(value)

    @field_validator("decision_required", mode="before")
    @classmethod
    def _coerce_decision_required(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
        return bool(value)

    @model_validator(mode="after")
    def _validate_answer_type(self) -> "PredictionRecord":
        if self.answer_type is not None and self.answer_type not in SUPPORTED_ANSWER_TYPES:
            raise ValueError(f"unsupported answer_type: {self.answer_type!r}")
        return self

    def key(self) -> tuple[str, str, str]:
        return self.case_id, self.variant_id, self.question_id


@dataclass(frozen=True)
class LoadedDataset:
    records: list[BaseModel]
    by_key: dict[tuple[str, str, str], BaseModel]


class PromptTask(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: str
    variant_id: str
    question_id: str
    answer_type: str | None = None
    decision_required: bool = False
    prompt: str
    system_prompt: str | None = None
    response_schema: dict[str, Any] | None = None
    policy: str = "evidence_required"

    @field_validator("case_id", "variant_id", "question_id", "prompt", "policy")
    @classmethod
    def _strip_prompt_fields(cls, value: str) -> str:
        value = _normalize_text(value)
        if not value:
            raise ValueError("field cannot be empty")
        return value

    @field_validator("answer_type")
    @classmethod
    def _strip_answer_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _normalize_text(value)
        if not value:
            return None
        return value

    @field_validator("decision_required", mode="before")
    @classmethod
    def _coerce_decision_required(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
        return bool(value)

    def key(self) -> tuple[str, str, str]:
        return self.case_id, self.variant_id, self.question_id


class PredictionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: Any
    decision: str | None = None
    evidence: list[str] = Field(default_factory=list)
    evidence_details: list[dict[str, Any]] | None = None
    missing_information: Any = Field(default_factory=list)
    explanation: str = ""


class ModelPrediction(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: str
    variant_id: str
    question_id: str
    answer: Any
    decision: str | None = None
    evidence: Any = Field(default_factory=list)
    evidence_details: Any = Field(default_factory=list)
    missing_information: Any = Field(default_factory=list)
    explanation: str = ""
    model: str | None = None
    provider: str | None = None
    run_id: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    status: str = "ok"
    error: str | None = None
    raw_response: Any = None

    @field_validator("case_id", "variant_id", "question_id", "status")
    @classmethod
    def _strip_result_fields(cls, value: str) -> str:
        value = _normalize_text(value)
        if not value:
            raise ValueError("field cannot be empty")
        return value

    @field_validator("decision")
    @classmethod
    def _strip_decision(cls, value: Any) -> str | None:
        if value is None:
            return None
        value = _normalize_text(value)
        if not value:
            return None
        return value

    @field_validator("missing_information", mode="before")
    @classmethod
    def _normalize_missing_information(cls, value: Any) -> Any:
        return _normalize_structured_empty(value)

    @field_validator("evidence_details", mode="before")
    @classmethod
    def _normalize_evidence_details(cls, value: Any) -> Any:
        return _normalize_structured_empty(value)

    def key(self) -> tuple[str, str, str]:
        return self.case_id, self.variant_id, self.question_id


def coerce_output_answer(answer_type: str | None, value: Any) -> Any:
    if answer_type is None or value is None:
        return value
    answer_type = _normalize_text(answer_type)

    def _as_text() -> str:
        return _normalize_text(value)

    if answer_type == "money":
        canonical = normalize_answer_value(answer_type, value)
        decimal_value = Decimal(canonical)
        return int(decimal_value) if decimal_value == decimal_value.to_integral() else float(decimal_value)
    if answer_type == "integer":
        return int(normalize_answer_value(answer_type, value))
    if answer_type == "boolean":
        return normalize_answer_value(answer_type, value) == "true"
    if answer_type in {"date", "datetime", "threshold"}:
        return normalize_answer_value(answer_type, value)
    if answer_type == "date_range":
        return normalize_answer_value(answer_type, value)
    if answer_type == "code_set":
        if isinstance(value, dict):
            accepted = [
                str(key).strip()
                for key, flag in value.items()
                if isinstance(flag, bool) and flag and str(key).strip()
            ]
            if accepted:
                canonical = normalize_answer_value(answer_type, accepted)
                return canonical.split("|") if canonical else []
            if all(isinstance(flag, bool) for flag in value.values()):
                return []
        try:
            canonical = normalize_answer_value(answer_type, value)
            return canonical.split("|") if canonical else []
        except ValueError:
            text = _as_text()
            if not text:
                raise
            tokens = [token.strip() for token in re.split(r"[|,;/\n]+", text) if token.strip()]
            if not tokens:
                raise
            for token in tokens:
                if any(ch.isspace() for ch in token) or not re.fullmatch(r"[A-Za-z0-9_:-]+", token):
                    raise ValueError(f"invalid code_set value: {value!r}")
            return sorted(dict.fromkeys(tokens))
    if answer_type == "json":
        return value
    if answer_type == "categorical":
        try:
            return normalize_answer_value(answer_type, value)
        except ValueError:
            return _as_text()
    if answer_type == "identifier":
        try:
            return normalize_answer_value(answer_type, value)
        except ValueError:
            return _as_text()
    if answer_type == "status":
        try:
            return normalize_answer_value(answer_type, value)
        except ValueError:
            return _as_text()
    return value
