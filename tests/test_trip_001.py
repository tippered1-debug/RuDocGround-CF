from __future__ import annotations

import json
import subprocess
import shutil
from pathlib import Path

import pytest

from rudocground.case_tools import CASE_PROMPT_COUNTS, CaseAuditError, audit_case, audit_source_fidelity, prepare_prompts
from rudocground.io import DataFormatError, load_gold, load_predictions
from rudocground.metrics import evaluate_report
from rudocground.models import ModelPrediction, PromptTask, coerce_output_answer, normalize_answer_value
from rudocground.runner import evaluate_run, run_model
from rudocground.providers.gemini_provider import GeminiProvider
from rudocground.providers.codex_cli_provider import CodexCliProvider, codex_diagnostics
from rudocground.providers.mock_provider import MockProvider


CASE_DIR = Path("data/cases/trip_001")
SOURCE_DIR = Path("data/source_documents/trip_001")
PROC_CASE_DIR = Path("data/cases/procurement_002")
PROC_SOURCE_DIR = Path("data/source_documents/procurement_002")
AUTH_CASE_DIR = Path("data/cases/authority_003")
AUTH_SOURCE_DIR = Path("data/source_documents/authority_003")
GOLD_PATH = Path("data/gold.jsonl")


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_case_gold(tmp_path: Path, case_id: str) -> Path:
    target = tmp_path / f"{case_id}_gold.jsonl"
    rows = [row for row in load_gold(GOLD_PATH).records if row.case_id == case_id]
    target.write_text(
        "\n".join(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return target


def _copy_case(tmp_path: Path) -> Path:
    target = tmp_path / "trip_001_case"
    shutil.copytree(CASE_DIR, target)
    return target


def _copy_sources(tmp_path: Path) -> Path:
    target = tmp_path / "trip_001_sources"
    shutil.copytree(SOURCE_DIR, target)
    return target


def _copy_procurement_case(tmp_path: Path) -> Path:
    target = tmp_path / "procurement_002_case"
    shutil.copytree(PROC_CASE_DIR, target)
    return target


def _copy_procurement_sources(tmp_path: Path) -> Path:
    target = tmp_path / "procurement_002_sources"
    shutil.copytree(PROC_SOURCE_DIR, target)
    return target


def _copy_authority_case(tmp_path: Path) -> Path:
    target = tmp_path / "authority_003_case"
    shutil.copytree(AUTH_CASE_DIR, target)
    return target


def _copy_authority_sources(tmp_path: Path) -> Path:
    target = tmp_path / "authority_003_sources"
    shutil.copytree(AUTH_SOURCE_DIR, target)
    return target


def _hash_map(directory: Path) -> dict[str, str]:
    import hashlib

    hashes: dict[str, str] = {}
    for file_path in sorted(directory.glob("*.docx")):
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        hashes[file_path.name] = digest
    return hashes


def _hash_map_any(directory: Path) -> dict[str, str]:
    import hashlib

    hashes: dict[str, str] = {}
    for file_path in sorted(directory.iterdir()):
        if file_path.is_file():
            digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
            hashes[file_path.name] = digest
    return hashes


def test_gold_has_both_cases_with_expected_counts():
    gold = load_gold(GOLD_PATH)
    assert len(gold.records) == 320
    trip_rows = [row for row in gold.records if row.case_id == "trip_001"]
    procurement_rows = [row for row in gold.records if row.case_id == "procurement_002"]
    authority_rows = [row for row in gold.records if row.case_id == "authority_003"]
    sla_rows = [row for row in gold.records if row.case_id == "sla_008"]
    assert len(trip_rows) == 34
    assert len(procurement_rows) == 30
    assert len(authority_rows) == 32
    assert len(sla_rows) == 32
    assert {row.variant_id for row in trip_rows} == {"A", "B"}
    assert {row.variant_id for row in procurement_rows} == {"A", "B"}
    assert {row.variant_id for row in authority_rows} == {"A", "B"}
    assert {row.variant_id for row in sla_rows} == {"A", "B"}
    assert {row.question_id for row in trip_rows} == {f"Q{i}" for i in range(1, 18)}
    assert {row.question_id for row in procurement_rows} == {f"Q{i}" for i in range(1, 16)}
    assert {row.question_id for row in authority_rows} == {f"Q{i}" for i in range(1, 17)}
    assert {row.question_id for row in sla_rows} == {f"Q{i}" for i in range(1, 17)}
    required_trip = {row.question_id for row in trip_rows if row.decision_required}
    required_proc = {row.question_id for row in procurement_rows if row.decision_required}
    required_auth = {row.question_id for row in authority_rows if row.decision_required}
    required_sla = {row.question_id for row in sla_rows if row.decision_required}
    assert required_trip == {"Q4", "Q6", "Q7", "Q8", "Q9", "Q11", "Q12", "Q14", "Q15", "Q16", "Q17"}
    assert required_proc == {"Q5", "Q6", "Q7", "Q8", "Q9", "Q11", "Q12", "Q15"}
    assert required_auth == {"Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10", "Q11", "Q12", "Q14", "Q15", "Q16"}
    assert required_sla == {"Q6", "Q7", "Q8", "Q9", "Q14", "Q15", "Q16"}


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("45 600,00 руб.", "45600"),
        ("45 600,00 ₽", "45600"),
        ("45 600", "45600"),
        ("9 000 руб.", "9000"),
        ("12 000,50", "12000.5"),
        ("45600.00", "45600"),
        (45600, "45600"),
        (45600.0, "45600"),
    ],
)
def test_russian_money_normalization(raw, expected):
    assert normalize_answer_value("money", raw) == expected


def test_datetime_normalization_supports_russian_months_and_iso():
    assert normalize_answer_value("datetime", "17 сентября 2026 г. в 12:26") == "2026-09-17T12:26:00"
    assert normalize_answer_value("datetime", "17 сентября 2026 г., 12:26") == "2026-09-17T12:26:00"
    assert normalize_answer_value("datetime", "17 сентября 2026 г.") == "2026-09-17T00:00:00"
    assert normalize_answer_value("datetime", "2026-09-17T12:26:00") == "2026-09-17T12:26:00"
    assert normalize_answer_value("identifier", "ООО «ТехРесурс».") == "ООО «ТехРесурс»"
    assert normalize_answer_value("status", "Июль 2026 г.") == "июль_2026"
    assert normalize_answer_value("status", "Учётная запись технически активна.") == "Учётная запись технически активна"
    assert normalize_answer_value("status", "Активна.") == "Активна"


def test_datetime_normalization_does_not_extract_spurious_dates_from_long_text():
    text = "В отчёте указано: 12 000 рублей за ночь с 14 по 18 сентября 2026 года. Подписание было 17 сентября 2026 г. в 12:26."
    with pytest.raises(ValueError, match="invalid datetime value"):
        normalize_answer_value("datetime", text)
    with pytest.raises(ValueError, match="invalid datetime value"):
        coerce_output_answer("datetime", text)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("свыше 10 000", ">10000"),
        ("превышает 10 000", ">10000"),
        ("больше 10 000", ">10000"),
        ("выше 10 000", ">10000"),
        ("не менее 10 000", ">=10000"),
        ("не более 10 000", "<=10000"),
        ("меньше 10 000", "<10000"),
        ("ниже 10 000", "<10000"),
    ],
)
def test_threshold_normalization_supports_russian_comparators(raw, expected):
    assert normalize_answer_value("threshold", raw) == expected


def test_code_set_normalization_requires_canonical_codes():
    assert normalize_answer_value("code_set", ["destination_address", "business_purpose_evidence"]) == "business_purpose_evidence|destination_address"
    assert coerce_output_answer("code_set", "destination_address | business_purpose_evidence") == ["business_purpose_evidence", "destination_address"]
    assert coerce_output_answer(
        "code_set",
        {
            "destination_address": True,
            "business_purpose_evidence": False,
        },
    ) == ["destination_address"]
    assert coerce_output_answer(
        "code_set",
        {
            "destination_address": False,
            "business_purpose_evidence": False,
        },
    ) == []
    with pytest.raises(ValueError, match="invalid code_set value"):
        normalize_answer_value("code_set", "Укажите адрес и деловую цель поездки")
    with pytest.raises(ValueError, match="invalid code_set value"):
        coerce_output_answer("code_set", "Укажите адрес и деловую цель поездки")


def test_prediction_structured_empty_fields_normalize_to_lists():
    prediction = ModelPrediction.model_validate(
        {
            "case_id": "trip_001",
            "variant_id": "A",
            "question_id": "Q1",
            "answer": 9000,
            "decision": None,
            "evidence": ["policy_01"],
            "missing_information": None,
            "evidence_details": None,
            "explanation": "",
        }
    )
    assert prediction.missing_information == []
    assert prediction.evidence_details == []


def test_case_has_exactly_12_documents_and_one_order_differs(tmp_path: Path):
    case_copy = _copy_case(tmp_path)
    assert len(list((case_copy / "A" / "documents").glob("*.docx"))) == 12
    assert len(list((case_copy / "B" / "documents").glob("*.docx"))) == 12

    hashes_a = _hash_map(case_copy / "A" / "documents")
    hashes_b = _hash_map(case_copy / "B" / "documents")

    shared = []
    differing = []
    for filename in sorted(hashes_a):
        if "86-ОД" in filename:
            differing.append(filename)
            continue
        shared.append(filename)
        assert hashes_a[filename] == hashes_b[filename]

    assert len(shared) == 11
    assert differing == ["02_Приказ_86-ОД.docx"]
    assert hashes_a["02_Приказ_86-ОД.docx"] != hashes_b["02_Приказ_86-ОД.docx"]

    audit_case(case_copy)


def test_required_evidence_doc_ids_exist():
    gold = load_gold(GOLD_PATH)
    manifest = json.loads((CASE_DIR / "manifest.json").read_text(encoding="utf-8"))
    manifest_doc_ids = {entry["doc_id"] for entry in manifest["documents"]}

    required_doc_ids = set()
    for row in gold.records:
        if row.case_id != "trip_001":
            continue
        for evidence in row.required_evidence:
            if isinstance(evidence, str) and "#" in evidence:
                required_doc_ids.add(evidence.split("#", 1)[0])

    assert required_doc_ids <= manifest_doc_ids


def test_authority_required_evidence_doc_ids_exist():
    gold = load_gold(GOLD_PATH)
    manifest = json.loads((AUTH_CASE_DIR / "manifest.json").read_text(encoding="utf-8"))
    manifest_doc_ids = {entry["doc_id"] for entry in manifest["documents"]}

    required_doc_ids = set()
    for row in gold.records:
        if row.case_id != "authority_003":
            continue
        for evidence in row.required_evidence:
            if isinstance(evidence, str) and "#" in evidence:
                required_doc_ids.add(evidence.split("#", 1)[0])

    assert required_doc_ids <= manifest_doc_ids


def test_source_fidelity_passes_and_missing_source_file_raises(tmp_path: Path):
    case_copy = _copy_case(tmp_path)
    source_copy = _copy_sources(tmp_path)

    summary = audit_source_fidelity(case_copy, source_copy)
    assert summary["documents_in_a"] == 12
    assert summary["documents_in_b"] == 12

    missing_source = source_copy / "04_Заявка.docx"
    missing_source.unlink()
    with pytest.raises(CaseAuditError, match="missing source file"):
        audit_source_fidelity(case_copy, source_copy)


def test_prepare_prompts_creates_all_prompt_files_and_uses_full_context(tmp_path: Path):
    case_copy = _copy_case(tmp_path)
    output_dir = tmp_path / "prompts"
    counts = prepare_prompts(case_copy, GOLD_PATH, output_dir)

    assert counts == {"A": 17, "B": 17, "all": 34}
    assert len(_read_jsonl(output_dir / "trip_001_A.jsonl")) == 17
    assert len(_read_jsonl(output_dir / "trip_001_B.jsonl")) == 17
    assert len(_read_jsonl(output_dir / "trip_001_all.jsonl")) == 34

    prompt_text = _read_jsonl(output_dir / "trip_001_all.jsonl")[0]["prompt"]
    assert "[DOCUMENT doc_id=policy_01]" in prompt_text
    assert "Decision is optional for this question" in prompt_text
    assert "В целях единообразного контроля командировочных расходов" in prompt_text
    assert "Проживание 15.09–16.09" in prompt_text
    assert "Документ подтверждает факт оплаты и точку отправления" in prompt_text


def test_prepare_prompts_sets_actual_schema_ids_and_allowed_labels_for_trip_001(tmp_path: Path):
    case_copy = _copy_case(tmp_path)
    output_dir = tmp_path / "prompts"
    counts = prepare_prompts(case_copy, GOLD_PATH, output_dir)
    assert counts == {"A": 17, "B": 17, "all": 34}

    rows = _read_jsonl(output_dir / "trip_001_all.jsonl")
    assert len(rows) == 34
    by_key = {(row["case_id"], row["variant_id"], row["question_id"]): row for row in rows}
    expected_trip_qids = {f"Q{i}" for i in range(1, 18)}
    assert {row["question_id"] for row in rows} == expected_trip_qids

    allowed_decisions = {}
    for row in rows:
        schema = row["response_schema"]
        assert schema["case_id"] == row["case_id"]
        assert schema["variant_id"] == row["variant_id"]
        assert schema["question_id"] == row["question_id"]
        assert schema["decision_required"] == row["decision_required"]
        if row["decision_required"]:
            labels = schema["allowed_decision_labels"]
            assert isinstance(labels, list)
            assert len(labels) >= 2
            allowed_decisions.setdefault(row["question_id"], labels)
            assert labels == allowed_decisions[row["question_id"]]
        else:
            assert schema["allowed_decision_labels"] == []

    assert allowed_decisions["Q4"] == ["is_a_reimbursement_cap", "not_a_reimbursement_cap"]
    assert allowed_decisions["Q6"] == ["max_allowable_hotel_cost", "not_max_allowable_hotel_cost"]
    assert allowed_decisions["Q7"] == ["reimburse", "partially_reimburse"]
    assert allowed_decisions["Q8"] == ["preapproved", "not_preapproved"]
    assert allowed_decisions["Q9"] == ["preapproval_not_final_reimbursement", "preapproval_is_final_reimbursement"]
    assert allowed_decisions["Q11"] == ["approved_in_time", "approved_after_deadline"]
    assert allowed_decisions["Q12"] == ["presence_and_business_activity_confirmed", "presence_or_business_activity_not_confirmed"]
    assert allowed_decisions["Q14"] == ["taxi_expense_supported", "taxi_expense_not_supported"]
    assert allowed_decisions["Q15"] == ["insufficient_information", "sufficient_information"]
    assert allowed_decisions["Q16"] == ["submitted_on_time", "submitted_late"]
    assert allowed_decisions["Q17"] == ["request_additional_documents", "no_additional_documents_needed"]

    q17 = by_key[("trip_001", "A", "Q17")]
    assert q17["response_schema"]["allowed_code_values"] == ["destination_address", "business_purpose_evidence"]
    assert q17["response_schema"]["answer_type"] == "code_set"


def test_prepare_prompts_sets_decision_labels_for_all_cases(tmp_path: Path):
    gold_rows = load_gold(GOLD_PATH).records
    gold_by_key = {(row.case_id, row.variant_id, row.question_id): row for row in gold_rows}
    gold_by_case_question = {}
    gold_values_by_case_question = {}
    output_dir = tmp_path / "prompts"
    combined_rows: list[dict] = []

    for case_id in CASE_PROMPT_COUNTS:
        case_dir = Path("data/cases") / case_id
        counts = prepare_prompts(case_dir, GOLD_PATH, output_dir)
        assert counts["all"] == CASE_PROMPT_COUNTS[case_id]
        rows = _read_jsonl(output_dir / f"{case_id}_all.jsonl")
        assert len(rows) == CASE_PROMPT_COUNTS[case_id]
        combined_rows.extend(rows)

    assert len(combined_rows) == 320
    assert len({(row["case_id"], row["variant_id"], row["question_id"]) for row in combined_rows}) == 320

    for row in combined_rows:
        key = (row["case_id"], row["variant_id"], row["question_id"])
        gold = gold_by_key[key]
        schema = row["response_schema"]
        assert schema["case_id"] == row["case_id"]
        assert schema["variant_id"] == row["variant_id"]
        assert schema["question_id"] == row["question_id"]

        if row["decision_required"]:
            labels = schema["allowed_decision_labels"]
            assert isinstance(labels, list)
            assert len(labels) >= 2
            assert gold.decision in labels
            pair_key = (row["case_id"], row["question_id"])
            if pair_key not in gold_by_case_question:
                gold_by_case_question[pair_key] = labels
            else:
                assert labels == gold_by_case_question[pair_key]
        else:
            assert schema["allowed_decision_labels"] == []
        answer_values = schema["allowed_answer_values"]
        if answer_values:
            assert isinstance(answer_values, list)
            assert len(answer_values) >= 2
            assert normalize_answer_value(row["answer_type"], gold.answer_normalized) in answer_values
            pair_key = (row["case_id"], row["question_id"])
            if pair_key not in gold_values_by_case_question:
                gold_values_by_case_question[pair_key] = answer_values
            else:
                assert answer_values == gold_values_by_case_question[pair_key]
        else:
            assert answer_values == []

        if row["answer_type"] == "code_set":
            assert schema["allowed_code_values"]
            assert isinstance(schema["allowed_code_values"], list)
        else:
            assert schema["allowed_code_values"] == []

        schema_text = json.dumps(schema, ensure_ascii=False)
        assert "gold_answer" not in schema_text
        assert "required_evidence" not in schema_text
        assert "must_change_from_other_variant" not in schema_text


def test_procurement_case_has_seven_documents_and_prompts(tmp_path: Path):
    case_copy = _copy_procurement_case(tmp_path)
    source_copy = _copy_procurement_sources(tmp_path)
    output_dir = tmp_path / "procurement_prompts"

    summary = audit_case(case_copy)
    assert summary is None
    source_summary = audit_source_fidelity(case_copy, source_copy)
    assert source_summary["documents_in_a"] == 7
    assert source_summary["documents_in_b"] == 7

    counts = prepare_prompts(case_copy, GOLD_PATH, output_dir)
    assert counts == {"A": 15, "B": 15, "all": 30}
    assert len(_read_jsonl(output_dir / "procurement_002_A.jsonl")) == 15
    assert len(_read_jsonl(output_dir / "procurement_002_B.jsonl")) == 15
    assert len(_read_jsonl(output_dir / "procurement_002_all.jsonl")) == 30

    prompt_a = _read_jsonl(output_dir / "procurement_002_A.jsonl")[0]["prompt"]
    prompt_b = _read_jsonl(output_dir / "procurement_002_B.jsonl")[0]["prompt"]
    assert "[DOCUMENT doc_id=procurement_policy]" in prompt_a
    assert "[DOCUMENT doc_id=temporary_order]" in prompt_a
    assert "Прямая закупка допустима при цене договора до 300 000 руб. включительно." in prompt_a
    assert "31 октября 2026 г. включительно." in prompt_a
    assert "15 октября 2026 г. включительно." in prompt_b


def test_authority_case_has_seven_documents_and_prompts(tmp_path: Path):
    case_copy = _copy_authority_case(tmp_path)
    source_copy = _copy_authority_sources(tmp_path)
    output_dir = tmp_path / "authority_prompts"

    summary = audit_case(case_copy)
    assert summary is None
    source_summary = audit_source_fidelity(case_copy, source_copy)
    assert source_summary["documents_in_a"] == 7
    assert source_summary["documents_in_b"] == 7

    counts = prepare_prompts(case_copy, GOLD_PATH, output_dir)
    assert counts == {"A": 16, "B": 16, "all": 32}
    assert len(_read_jsonl(output_dir / "authority_003_A.jsonl")) == 16
    assert len(_read_jsonl(output_dir / "authority_003_B.jsonl")) == 16
    assert len(_read_jsonl(output_dir / "authority_003_all.jsonl")) == 32

    prompt_a = _read_jsonl(output_dir / "authority_003_all.jsonl")[0]["prompt"]
    prompt_b = _read_jsonl(output_dir / "authority_003_all.jsonl")[1]["prompt"]
    assert "[DOCUMENT doc_id=contract_policy]" in prompt_a
    assert "[DOCUMENT doc_id=power_of_attorney_A]" in prompt_a
    assert "[DOCUMENT doc_id=power_of_attorney_B]" in prompt_b
    assert "договоры приобретения и поставки компьютерного, серверного и сетевого оборудования" in prompt_a
    assert "договоры технического обслуживания, ремонта и технической поддержки компьютерного, серверного и сетевого оборудования" in prompt_b

    gold = load_gold(GOLD_PATH)
    auth_rows = [row for row in gold.records if row.case_id == "authority_003"]
    q6_a = next(row for row in auth_rows if row.question_id == "Q6" and row.variant_id == "A")
    q6_b = next(row for row in auth_rows if row.question_id == "Q6" and row.variant_id == "B")
    q13_a = next(row for row in auth_rows if row.question_id == "Q13" and row.variant_id == "A")
    q13_b = next(row for row in auth_rows if row.question_id == "Q13" and row.variant_id == "B")
    assert q6_a.answer_normalized != q6_b.answer_normalized
    assert q13_a.answer_normalized == q13_b.answer_normalized


def test_procurement_perfect_predictions_produce_ideal_metrics(tmp_path: Path):
    gold_path = _write_case_gold(tmp_path, "procurement_002")
    pred_path = tmp_path / "procurement_perfect.jsonl"
    pred_path.write_text(
        "\n".join(
            json.dumps(row.model_dump(mode="json"), ensure_ascii=False)
            for row in load_gold(gold_path).records
        )
        + "\n",
        encoding="utf-8",
    )
    report = evaluate_report(str(gold_path), str(pred_path))
    assert report.issues == []
    for metric in (
        "answer_accuracy",
        "decision_accuracy",
        "evidence_precision",
        "evidence_recall",
        "evidence_f1",
        "missing_information_accuracy",
    ):
        assert report.overall[metric] == pytest.approx(1.0)
    assert report.counterfactual["flip_score"] == pytest.approx(1.0)
    assert report.counterfactual["invariance_score"] == pytest.approx(1.0)


def test_perfect_predictions_produce_ideal_metrics():
    report = evaluate_report(str(GOLD_PATH), "results/perfect.jsonl")
    assert report.issues == []
    for metric in (
        "answer_accuracy",
        "decision_accuracy",
        "evidence_precision",
        "evidence_recall",
        "evidence_f1",
        "missing_information_accuracy",
    ):
        assert report.overall[metric] == pytest.approx(1.0)
    assert report.overall["unsupported_evidence_rate"] == pytest.approx(0.0)
    assert report.counterfactual["flip_score"] == pytest.approx(1.0)
    assert report.counterfactual["invariance_score"] == pytest.approx(1.0)


def test_q1_decision_is_ignored_and_q7_decision_is_scored(tmp_path: Path):
    gold_path = tmp_path / "gold.jsonl"
    pred_path = tmp_path / "pred.jsonl"
    gold_rows = load_gold(GOLD_PATH).records
    q1 = next(row for row in gold_rows if row.question_id == "Q1" and row.variant_id == "A")
    q7 = next(row for row in gold_rows if row.question_id == "Q7" and row.variant_id == "A")
    gold_path.write_text(
        "\n".join(
            json.dumps(row.model_dump(mode="json"), ensure_ascii=False)
            for row in [q1, q7]
        )
        + "\n",
        encoding="utf-8",
    )
    pred_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "trip_001",
                        "variant_id": "A",
                        "question_id": "Q1",
                        "answer": 9000,
                        "decision": "fully_supported",
                        "evidence": ["policy_01"],
                        "missing_information": [],
                        "explanation": "Базовый лимит для руководителя проекта составляет 9000 рублей.",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "case_id": "trip_001",
                        "variant_id": "A",
                        "question_id": "Q7",
                        "answer": 45600,
                        "decision": "wrong_decision",
                        "evidence": ["policy_01", "order_86_A", "hotel_invoice", "hotel_payment"],
                        "missing_information": [],
                        "explanation": "Возмещение рассчитывается по документам.",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    report = evaluate_report(str(gold_path), str(pred_path))
    q1_row = next(row for row in report.records if row["key"]["question_id"] == "Q1")
    q7_row = next(row for row in report.records if row["key"]["question_id"] == "Q7")
    assert q1_row["decision_correct"] is None
    assert q1_row["answer_correct"] is True
    assert q1_row["evidence_f1"] == pytest.approx(1.0)
    assert q7_row["decision_correct"] is False
    assert report.overall["decision_required_count"] == 1
    assert report.overall["decision_accuracy"] == pytest.approx(0.0)
    assert report.overall["answer_accuracy"] == pytest.approx(1.0)


def test_q1_null_decision_is_not_scored(tmp_path: Path):
    gold_path = tmp_path / "gold_q1.jsonl"
    pred_path = tmp_path / "pred_q1.jsonl"
    gold_row = next(row for row in load_gold(GOLD_PATH).records if row.question_id == "Q1" and row.variant_id == "A")
    gold_path.write_text(json.dumps(gold_row.model_dump(mode="json"), ensure_ascii=False) + "\n", encoding="utf-8")
    pred_path.write_text(
        json.dumps(
            {
                "case_id": "trip_001",
                "variant_id": "A",
                "question_id": "Q1",
                "answer": 9000,
                "decision": None,
                "evidence": ["policy_01"],
                "missing_information": [],
                "explanation": "Базовый лимит для руководителя проекта составляет 9000 рублей.",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    report = evaluate_report(str(gold_path), str(pred_path))
    row = report.records[0]
    assert row["decision_correct"] is None
    assert report.overall["decision_required_count"] == 0
    assert report.overall["decision_accuracy"] == pytest.approx(0.0)


def test_broken_predictions_reduce_counterfactual_and_evidence_metrics():
    report = evaluate_report(str(GOLD_PATH), "results/broken.jsonl")
    assert report.counterfactual["flip_score"] < 1.0
    assert report.counterfactual["invariance_score"] < 1.0
    assert report.overall["evidence_f1"] < 1.0
    assert report.overall["unsupported_evidence_rate"] > 0.0


def test_invented_address_is_not_treated_as_an_answer():
    predictions = load_predictions("results/broken.jsonl")
    row = next(record for record in predictions.records if record.question_id == "Q15" and record.variant_id == "A")
    assert row.answer_normalized is False
    assert row.model_extra["destination_address"].startswith("г. Казань")


def test_duplicate_key_in_partial_predictions_raises_clear_error():
    with pytest.raises(DataFormatError, match="duplicate key"):
        load_predictions("results/partial.jsonl")


def test_partial_predictions_surface_missing_answers_and_invalid_rows():
    report = evaluate_report(str(GOLD_PATH), "results/partial.jsonl")
    assert any(issue["kind"] == "missing_prediction" for issue in report.issues)
    assert any(issue["kind"] == "duplicate_key" for issue in report.issues)
    assert any(issue["kind"] == "invalid_answer" for issue in report.issues)
    assert report.overall["count"] < len(load_gold(GOLD_PATH).records)


def _mock_prediction_from_gold(row, *, answer=None, evidence=None) -> ModelPrediction:
    expected_evidence = [
        item.split("#", 1)[0]
        for item in row.required_evidence
        if isinstance(item, str) and item
    ]
    return ModelPrediction(
        case_id=row.case_id,
        variant_id=row.variant_id,
        question_id=row.question_id,
        answer=row.answer_normalized if answer is None else answer,
        decision=row.decision,
        evidence=list(expected_evidence if evidence is None else evidence),
        missing_information=list(row.missing_information),
        explanation="",
        model="mock-model",
        provider="mock",
        status="ok",
        error=None,
        raw_response={"mock": True},
    )


def _mock_provider_from_gold(overrides: dict[tuple[str, str, str], dict | Exception] | None = None) -> MockProvider:
    gold = load_gold(GOLD_PATH)
    responses = {}
    overrides = overrides or {}
    for row in gold.records:
        key = row.key()
        override = overrides.get(key)
        if isinstance(override, Exception):
            responses[key] = override
        elif isinstance(override, dict):
            responses[key] = override
        else:
            responses[key] = _mock_prediction_from_gold(row)
    return MockProvider(responses=responses)


def test_dry_run_does_not_call_provider(tmp_path: Path):
    output = tmp_path / "dry.jsonl"
    provider = _mock_provider_from_gold()
    summary = run_model(
        "prompts/trip_001_all.jsonl",
        "mock",
        "mock-model",
        output,
        provider=provider,
        dry_run=True,
    )
    assert summary.selected_tasks == 34
    assert provider.calls == []
    assert not output.exists()


def test_limit_and_resume_skip_completed_tasks(tmp_path: Path):
    output = tmp_path / "limit.jsonl"
    provider = _mock_provider_from_gold()
    first = run_model(
        "prompts/trip_001_all.jsonl",
        "mock",
        "mock-model",
        output,
        provider=provider,
        limit=2,
    )
    assert first.successful == 2
    assert len(provider.calls) == 2
    second = run_model(
        "prompts/trip_001_all.jsonl",
        "mock",
        "mock-model",
        output,
        provider=provider,
        limit=2,
        resume=True,
    )
    assert second.skipped == 2
    assert len(provider.calls) == 2


def test_resume_retries_error_rows(tmp_path: Path):
    output = tmp_path / "resume_error.jsonl"
    gold = load_gold(GOLD_PATH)
    first_key = gold.records[0].key()
    error_provider = _mock_provider_from_gold({first_key: RuntimeError("boom")})
    run_model(
        "prompts/trip_001_all.jsonl",
        "mock",
        "mock-model",
        output,
        provider=error_provider,
        limit=1,
    )
    rows = _read_jsonl(output)
    assert rows[0]["status"] == "error"

    success_provider = _mock_provider_from_gold()
    run_model(
        "prompts/trip_001_all.jsonl",
        "mock",
        "mock-model",
        output,
        provider=success_provider,
        limit=1,
        resume=True,
    )
    rows = _read_jsonl(output)
    assert rows[0]["status"] == "ok"
    assert len(success_provider.calls) == 1


def test_single_task_error_does_not_stop_run(tmp_path: Path):
    output = tmp_path / "error.jsonl"
    gold = load_gold(GOLD_PATH)
    bad_key = gold.records[0].key()
    provider = _mock_provider_from_gold({bad_key: RuntimeError("boom")})
    summary = run_model(
        "prompts/trip_001_all.jsonl",
        "mock",
        "mock-model",
        output,
        provider=provider,
        limit=3,
    )
    assert summary.failed == 1
    rows = _read_jsonl(output)
    assert len(rows) == 3
    assert any(row["status"] == "error" for row in rows)


def test_malformed_output_is_recorded_as_error(tmp_path: Path):
    output = tmp_path / "malformed.jsonl"
    gold = load_gold(GOLD_PATH)
    bad_key = gold.records[1].key()
    provider = _mock_provider_from_gold({bad_key: {"decision": "accept"}})
    summary = run_model(
        "prompts/trip_001_all.jsonl",
        "mock",
        "mock-model",
        output,
        provider=provider,
        limit=2,
    )
    assert summary.failed == 1
    rows = _read_jsonl(output)
    assert any(row["status"] == "error" for row in rows)


def test_extra_metadata_does_not_break_evaluator(tmp_path: Path):
    output = tmp_path / "metadata.jsonl"
    gold_path = _write_case_gold(tmp_path, "trip_001")
    provider = _mock_provider_from_gold()
    run_model(
        "prompts/trip_001_all.jsonl",
        "mock",
        "mock-model",
        output,
        provider=provider,
        limit=4,
    )
    report = evaluate_report(str(gold_path), str(output))
    assert report.overall["count"] == 4


def test_perfect_mock_gives_all_metrics_1(tmp_path: Path):
    output = tmp_path / "perfect.jsonl"
    gold_path = _write_case_gold(tmp_path, "trip_001")
    provider = _mock_provider_from_gold()
    run_model(
        "prompts/trip_001_all.jsonl",
        "mock",
        "mock-model",
        output,
        provider=provider,
    )
    report = evaluate_report(str(gold_path), str(output))
    assert report.overall["answer_accuracy"] == pytest.approx(1.0)
    assert report.overall["decision_accuracy"] == pytest.approx(1.0)
    assert report.overall["evidence_f1"] == pytest.approx(1.0)
    assert report.counterfactual["flip_score"] == pytest.approx(1.0)
    assert report.counterfactual["invariance_score"] == pytest.approx(1.0)


def test_repeating_a_answers_for_q6_q7_in_b_yields_flip_score_zero(tmp_path: Path):
    output = tmp_path / "flip_zero.jsonl"
    gold_path = _write_case_gold(tmp_path, "trip_001")
    gold = load_gold(GOLD_PATH)
    trip_rows = [row for row in gold.records if row.case_id == "trip_001"]
    a_answers = {
        row.question_id: row
        for row in trip_rows
        if row.variant_id == "A" and row.question_id in {"Q6", "Q7"}
    }
    responses = {}
    for row in trip_rows:
        key = row.key()
        if row.variant_id == "B" and row.question_id in {"Q6", "Q7"}:
            source = a_answers[row.question_id]
            responses[key] = _mock_prediction_from_gold(row, answer=source.answer_normalized)
        else:
            responses[key] = _mock_prediction_from_gold(row)
    provider = MockProvider(responses=responses)
    run_model(
        "prompts/trip_001_all.jsonl",
        "mock",
        "mock-model",
        output,
        provider=provider,
    )
    report = evaluate_report(str(gold_path), str(output))
    assert report.counterfactual["flip_score"] == pytest.approx(0.0)


def test_evaluate_run_writes_json_and_csv(tmp_path: Path):
    output = tmp_path / "run.jsonl"
    report_path = tmp_path / "run_report.json"
    provider = _mock_provider_from_gold()
    run_model(
        "prompts/trip_001_all.jsonl",
        "mock",
        "mock-model",
        output,
        provider=provider,
        limit=2,
    )
    report = evaluate_run(GOLD_PATH, output, report_path)
    assert report_path.exists()
    assert report_path.with_suffix(".csv").exists()
    assert report["overall"]["count"] == 2


def test_gemini_provider_parses_structured_output_and_records_raw_response():
    class FakeUsage:
        prompt_token_count = 11
        candidates_token_count = 7

    class FakeResponse:
        def __init__(self) -> None:
            self.parsed = ModelPrediction(
                case_id="trip_001",
                variant_id="A",
                question_id="Q1",
                answer="42",
                decision="accept",
                evidence=["doc#loc"],
                missing_information=[],
                explanation="done",
            )
            self.usage_metadata = FakeUsage()

        def model_dump(self, mode="json"):
            return {"raw": True, "mode": mode}

    class FakeModels:
        def __init__(self) -> None:
            self.calls = 0

        def generate_content(self, *, model, contents, config):
            self.calls += 1
            assert model == "gemini-2.5-flash"
            assert contents[0] == "sys"
            assert contents[1] == "prompt"
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    provider = GeminiProvider(model="gemini-2.5-flash", client=FakeClient())
    task = PromptTask(
        case_id="trip_001",
        variant_id="A",
        question_id="Q1",
        prompt="prompt",
        system_prompt="sys",
        response_schema={
            "case_id": "trip_001",
            "variant_id": "A",
            "question_id": "Q1",
            "answer": None,
            "decision": "",
            "evidence": [],
            "missing_information": [],
            "explanation": "",
        },
    )
    prediction = provider.generate(task)
    assert prediction.provider == "gemini"
    assert prediction.model == "gemini-2.5-flash"
    assert prediction.input_tokens == 11
    assert prediction.output_tokens == 7
    assert prediction.raw_response == {"raw": True, "mode": "json"}


def test_gemini_provider_retries_transient_errors():
    class RetryError(Exception):
        code = 429

    class FakeResponse:
        parsed = ModelPrediction(
            case_id="trip_001",
            variant_id="A",
            question_id="Q1",
            answer="42",
            decision="accept",
            evidence=[],
            missing_information=[],
            explanation="",
        )
        usage_metadata = None

        def model_dump(self, mode="json"):
            return {"raw": True}

    class FakeModels:
        def __init__(self) -> None:
            self.calls = 0

        def generate_content(self, *, model, contents, config):
            self.calls += 1
            if self.calls == 1:
                raise RetryError("rate limited")
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    provider = GeminiProvider(model="gemini-2.5-flash", max_retries=2, client=FakeClient())
    task = PromptTask(
        case_id="trip_001",
        variant_id="A",
        question_id="Q1",
        prompt="prompt",
        system_prompt="sys",
        response_schema={
            "case_id": "trip_001",
            "variant_id": "A",
            "question_id": "Q1",
            "answer": None,
            "decision": "",
            "evidence": [],
            "missing_information": [],
            "explanation": "",
        },
    )
    prediction = provider.generate(task)
    assert prediction.status == "ok"


def test_gemini_provider_retries_429_with_retry_delay(monkeypatch):
    import rudocground.providers.gemini_provider as gemini_module

    sleeps: list[float] = []
    monkeypatch.setattr(gemini_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(gemini_module.random, "uniform", lambda a, b: 0.05)

    class RetryDelayError(Exception):
        code = 429
        status = "RESOURCE_EXHAUSTED"
        body = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "7s",
                    }
                ]
            }
        }

    class FakeResponse:
        parsed = ModelPrediction(
            case_id="trip_001",
            variant_id="A",
            question_id="Q1",
            answer="42",
            decision="accept",
            evidence=[],
            missing_information=[],
            explanation="",
        )
        usage_metadata = None

        def model_dump(self, mode="json"):
            return {"raw": True}

    class FakeModels:
        def __init__(self) -> None:
            self.calls = 0

        def generate_content(self, *, model, contents, config):
            self.calls += 1
            if self.calls == 1:
                raise RetryDelayError("rate limited")
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    provider = GeminiProvider(model="gemini-2.5-flash", max_retries=2, client=FakeClient())
    task = PromptTask(
        case_id="trip_001",
        variant_id="A",
        question_id="Q1",
        prompt="prompt",
        system_prompt="sys",
        response_schema={
            "case_id": "trip_001",
            "variant_id": "A",
            "question_id": "Q1",
            "answer": None,
            "decision": None,
            "evidence": [],
            "missing_information": [],
            "explanation": "",
        },
    )
    prediction = provider.generate(task)
    assert prediction.status == "ok"
    assert provider.client.models.calls == 2
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(7.05)


def test_gemini_provider_retries_429_without_retry_delay(monkeypatch):
    import rudocground.providers.gemini_provider as gemini_module

    sleeps: list[float] = []
    monkeypatch.setattr(gemini_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(gemini_module.random, "uniform", lambda a, b: 0.05)

    class RetryLimitError(Exception):
        code = 429
        status = "RESOURCE_EXHAUSTED"
        body = {"error": {"details": []}}

    class FakeResponse:
        parsed = ModelPrediction(
            case_id="trip_001",
            variant_id="A",
            question_id="Q1",
            answer="42",
            decision="accept",
            evidence=[],
            missing_information=[],
            explanation="",
        )
        usage_metadata = None

        def model_dump(self, mode="json"):
            return {"raw": True}

    class FakeModels:
        def __init__(self) -> None:
            self.calls = 0

        def generate_content(self, *, model, contents, config):
            self.calls += 1
            if self.calls == 1:
                raise RetryLimitError("rate limited")
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    provider = GeminiProvider(model="gemini-2.5-flash", max_retries=2, client=FakeClient())
    task = PromptTask(
        case_id="trip_001",
        variant_id="A",
        question_id="Q1",
        prompt="prompt",
        system_prompt="sys",
        response_schema={
            "case_id": "trip_001",
            "variant_id": "A",
            "question_id": "Q1",
            "answer": None,
            "decision": None,
            "evidence": [],
            "missing_information": [],
            "explanation": "",
        },
    )
    prediction = provider.generate(task)
    assert prediction.status == "ok"
    assert provider.client.models.calls == 2
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(15.05)


def test_gemini_provider_succeeds_after_multiple_retries(monkeypatch):
    import rudocground.providers.gemini_provider as gemini_module

    sleeps: list[float] = []
    monkeypatch.setattr(gemini_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(gemini_module.random, "uniform", lambda a, b: 0.05)

    class TemporaryError(Exception):
        code = 503
        status = "UNAVAILABLE"

    class FakeResponse:
        parsed = ModelPrediction(
            case_id="trip_001",
            variant_id="A",
            question_id="Q1",
            answer="42",
            decision="accept",
            evidence=[],
            missing_information=[],
            explanation="",
        )
        usage_metadata = None

        def model_dump(self, mode="json"):
            return {"raw": True}

    class FakeModels:
        def __init__(self) -> None:
            self.calls = 0

        def generate_content(self, *, model, contents, config):
            self.calls += 1
            if self.calls < 3:
                raise TemporaryError("temporary failure")
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    provider = GeminiProvider(model="gemini-2.5-flash", max_retries=5, client=FakeClient())
    task = PromptTask(
        case_id="trip_001",
        variant_id="A",
        question_id="Q1",
        prompt="prompt",
        system_prompt="sys",
        response_schema={
            "case_id": "trip_001",
            "variant_id": "A",
            "question_id": "Q1",
            "answer": None,
            "decision": None,
            "evidence": [],
            "missing_information": [],
            "explanation": "",
        },
    )
    prediction = provider.generate(task)
    assert prediction.status == "ok"
    assert provider.client.models.calls == 3
    assert len(sleeps) == 2


def test_gemini_provider_stops_after_max_attempts(monkeypatch):
    import rudocground.providers.gemini_provider as gemini_module

    sleeps: list[float] = []
    monkeypatch.setattr(gemini_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(gemini_module.random, "uniform", lambda a, b: 0.05)

    class PermanentError(Exception):
        code = 500
        status = "INTERNAL"

    class FakeModels:
        def __init__(self) -> None:
            self.calls = 0

        def generate_content(self, *, model, contents, config):
            self.calls += 1
            raise PermanentError("server error")

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    provider = GeminiProvider(model="gemini-2.5-flash", max_retries=2, client=FakeClient())
    task = PromptTask(
        case_id="trip_001",
        variant_id="A",
        question_id="Q1",
        prompt="prompt",
        system_prompt="sys",
        response_schema={
            "case_id": "trip_001",
            "variant_id": "A",
            "question_id": "Q1",
            "answer": None,
            "decision": None,
            "evidence": [],
            "missing_information": [],
            "explanation": "",
        },
    )
    with pytest.raises(PermanentError):
        provider.generate(task)
    assert provider.client.models.calls == 2
    assert len(sleeps) == 1


def test_codex_provider_uses_isolated_subprocesses_and_stdin(tmp_path: Path):
    import json as _json
    import rudocground.providers.codex_cli_provider as codex_module

    calls = []

    class FakeTempDir:
        def __init__(self, path: Path) -> None:
            self.name = str(path)

        def __enter__(self):
            Path(self.name).mkdir(parents=True, exist_ok=True)
            return self.name

        def __exit__(self, exc_type, exc, tb):
            return False

    def tempdir_factory():
        idx = len(calls) + 1
        return FakeTempDir(tmp_path / f"td-{idx}")

    def fake_run(cmd, input, text, capture_output, cwd):
        assert "--ephemeral" in cmd
        assert "--skip-git-repo-check" in cmd
        assert "--sandbox" in cmd and "read-only" in cmd
        assert "--ask-for-approval" in cmd and "never" in cmd
        assert "--ignore-user-config" in cmd
        assert "--ignore-rules" in cmd
        assert "--json" in cmd
        assert "-o" in cmd
        assert "data/gold.jsonl" not in cmd
        assert "prompts/trip_001_all.jsonl" not in cmd
        assert cwd.startswith(str(tmp_path))
        calls.append({"cmd": list(cmd), "input": input, "cwd": cwd})
        response_file = Path(cmd[cmd.index("-o") + 1])
        response = {
            "answer": "45 600,00 руб.",
            "decision": "reimburse",
            "evidence": ["policy_01#appendix_1"],
            "evidence_details": [{"doc_id": "policy_01", "locator": "appendix"}],
            "missing_information": None,
            "explanation": "ok",
        }
        response_file.write_text(_json.dumps(response, ensure_ascii=False), encoding="utf-8")
        stdout = "\n".join(
            [
                '{"type":"tool.started","tool":"web_search"}',
                '{"type":"turn.completed"}',
            ]
        )
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="stderr")

    provider = CodexCliProvider(model="codex-default", client_runner=fake_run, tempdir_factory=tempdir_factory, codex_version_override="codex-cli test")
    task1 = PromptTask(
        case_id="trip_001",
        variant_id="A",
        question_id="Q6",
        prompt="prompt 1",
        system_prompt="sys",
        response_schema={
            "case_id": "trip_001",
            "variant_id": "A",
            "question_id": "Q6",
            "answer": None,
            "decision": None,
            "evidence": [],
            "evidence_details": [],
            "missing_information": [],
            "explanation": "",
        },
    )
    task2 = task1.model_copy(update={"question_id": "Q7", "prompt": "prompt 2", "variant_id": "B"})
    pred1 = provider.generate(task1)
    pred2 = provider.generate(task2)
    assert pred1.provider == "codex_cli"
    assert pred1.raw_response["codex_cli_version"] == "codex-cli test"
    assert pred1.raw_response["tool_use_detected"] is True
    assert pred1.raw_response["evaluation_contaminated"] is True
    assert len(calls) == 2
    assert calls[0]["cwd"] != calls[1]["cwd"]
    assert "prompt 1" in calls[0]["input"]
    assert "prompt 2" in calls[1]["input"]
    assert pred1.raw_response["response"]["answer"] == "45 600,00 руб."
    assert pred2.raw_response["response"]["answer"] == "45 600,00 руб."

    output = tmp_path / "codex-normalized.jsonl"
    run_model(
        "prompts/trip_001_all.jsonl",
        "codex",
        "codex-default",
        output,
        provider=provider,
        limit=1,
    )
    normalized = _read_jsonl(output)[0]
    assert normalized["answer"] == 45600
    assert normalized["evidence"] == ["policy_01"]


def test_codex_provider_builds_task_specific_output_schema_for_trip_001(tmp_path: Path):
    import rudocground.providers.codex_cli_provider as codex_module

    case_copy = _copy_case(tmp_path)
    prompt_dir = tmp_path / "prompts"
    prepare_prompts(case_copy, GOLD_PATH, prompt_dir)
    prompt_rows = _read_jsonl(prompt_dir / "trip_001_all.jsonl")
    row_map = {
        (row["case_id"], row["variant_id"], row["question_id"]): row
        for row in prompt_rows
        if row["question_id"] in {"Q6", "Q9", "Q16", "Q17"}
    }
    captured: list[dict] = []

    class FakeTempDir:
        def __init__(self, path: Path) -> None:
            self.name = str(path)

        def __enter__(self):
            Path(self.name).mkdir(parents=True, exist_ok=True)
            return self.name

        def __exit__(self, exc_type, exc, tb):
            return False

    def tempdir_factory():
        return FakeTempDir(tmp_path / f"td-{len(captured) + 1}")

    def fake_run(cmd, input, text, capture_output, cwd):
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "gpt-5.4"
        schema_path = Path(cmd[cmd.index("--output-schema") + 1])
        response_file = Path(cmd[cmd.index("-o") + 1])
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        captured.append(schema)
        decision_enum = schema["properties"]["decision"].get("enum", [])
        response = {
            "answer": "placeholder",
            "decision": decision_enum[0] if decision_enum else "placeholder",
            "evidence": ["transport_pack"],
            "evidence_details": [{"doc_id": "transport_pack", "locator": "taxi_2"}],
            "missing_information": ["destination_address", "business_purpose_evidence"],
            "explanation": "ok",
        }
        if decision_enum == ["request_additional_documents", "no_additional_documents_needed"]:
            response["answer"] = {
                "destination_address": True,
                "business_purpose_evidence": True,
            }
        elif decision_enum == ["max_allowable_hotel_cost", "not_max_allowable_hotel_cost"]:
            response["answer"] = "48000"
        elif decision_enum == ["preapproval_not_final_reimbursement", "preapproval_is_final_reimbursement"]:
            response["answer"] = True
        elif decision_enum == ["submitted_on_time", "submitted_late"]:
            response["answer"] = True
        response_file.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"type":"turn.completed"}\n', stderr="")

    provider = CodexCliProvider(model="gpt-5.4", client_runner=fake_run, tempdir_factory=tempdir_factory, codex_version_override="codex-cli test")
    selected = [
        PromptTask.model_validate(row_map[("trip_001", variant, qid)])
        for variant in ("A", "B")
        for qid in ("Q6", "Q9", "Q16", "Q17")
    ]
    for task in selected:
        prediction = provider.generate(task)
        assert prediction.status == "ok"

    assert len(captured) == 8
    schema_q6 = next(schema for schema in captured if schema["properties"]["decision"]["enum"] == ["max_allowable_hotel_cost", "not_max_allowable_hotel_cost"])
    schema_q9 = next(schema for schema in captured if schema["properties"]["decision"]["enum"] == ["preapproval_not_final_reimbursement", "preapproval_is_final_reimbursement"])
    schema_q16 = next(schema for schema in captured if schema["properties"]["decision"]["enum"] == ["submitted_on_time", "submitted_late"])
    schema_q17 = next(schema for schema in captured if schema["properties"]["decision"]["enum"] == ["request_additional_documents", "no_additional_documents_needed"])

    for schema in (schema_q6, schema_q9, schema_q16, schema_q17):
        assert schema["properties"]["decision"]["type"] == "string"
        assert "null" not in json.dumps(schema["properties"]["decision"], ensure_ascii=False)

    assert schema_q17["properties"]["answer"]["type"] == "object"
    assert schema_q17["properties"]["answer"]["properties"] == {
        "destination_address": {"type": "boolean"},
        "business_purpose_evidence": {"type": "boolean"},
    }
    assert schema_q17["properties"]["answer"]["required"] == ["destination_address", "business_purpose_evidence"]
    assert schema_q17["properties"]["answer"]["additionalProperties"] is False
    assert "uniqueItems" not in json.dumps(schema_q17["properties"]["answer"], ensure_ascii=False)

    q17_schemas = [
        schema
        for schema in captured
        if schema["properties"]["decision"]["enum"] == ["request_additional_documents", "no_additional_documents_needed"]
    ]
    assert len(q17_schemas) == 2
    assert q17_schemas[0] == q17_schemas[1]


def test_codex_provider_builds_task_specific_output_schema_for_all_cases(tmp_path: Path):
    import rudocground.providers.codex_cli_provider as codex_module

    output_dir = tmp_path / "prompts"
    all_rows: list[dict] = []
    gold_map = {
        (row.case_id, row.variant_id, row.question_id): row
        for row in load_gold(GOLD_PATH).records
    }
    for case_id in CASE_PROMPT_COUNTS:
        case_dir = Path("data/cases") / case_id
        prepare_prompts(case_dir, GOLD_PATH, output_dir)
        all_rows.extend(_read_jsonl(output_dir / f"{case_id}_all.jsonl"))

    captured: list[dict] = []
    row_iter = iter(all_rows)

    class FakeTempDir:
        def __init__(self, path: Path) -> None:
            self.name = str(path)

        def __enter__(self):
            Path(self.name).mkdir(parents=True, exist_ok=True)
            return self.name

        def __exit__(self, exc_type, exc, tb):
            return False

    def tempdir_factory():
        return FakeTempDir(tmp_path / f"td-{len(captured) + 1}")

    def fake_run(cmd, input, text, capture_output, cwd):
        schema_path = Path(cmd[cmd.index("--output-schema") + 1])
        response_file = Path(cmd[cmd.index("-o") + 1])
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        current_row = next(row_iter)
        gold_row = gold_map[(current_row["case_id"], current_row["variant_id"], current_row["question_id"])]
        captured.append(schema)
        response = {
            "answer": gold_row.answer_normalized,
            "decision": schema["properties"]["decision"].get("enum", ["placeholder"])[0],
            "evidence": ["doc_1"],
            "evidence_details": [{"doc_id": "doc_1", "locator": "p.1"}],
            "missing_information": [],
            "explanation": "ok",
        }
        if schema["properties"]["answer"].get("type") == "object":
            response["answer"] = {
                key: idx == 0
                for idx, key in enumerate(schema["properties"]["answer"].get("properties", {}).keys())
            }
        response_file.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"type":"turn.completed"}\n', stderr="")

    provider = CodexCliProvider(model="gpt-5.4", client_runner=fake_run, tempdir_factory=tempdir_factory, codex_version_override="codex-cli test")
    for row in all_rows:
        prediction = provider.generate(PromptTask.model_validate(row))
        assert prediction.status == "ok"

    assert len(captured) == 320
    for schema, row in zip(captured, all_rows):
        if row["decision_required"]:
            decision_enum = schema["properties"]["decision"].get("enum")
            assert isinstance(decision_enum, list)
            assert len(decision_enum) >= 2
        if row["answer_type"] == "code_set":
            answer_schema = schema["properties"]["answer"]
            assert answer_schema["type"] == "object"
            assert list(answer_schema["properties"].keys()) == row["response_schema"]["allowed_code_values"]
            assert answer_schema["required"] == row["response_schema"]["allowed_code_values"]
            assert answer_schema["additionalProperties"] is False
            assert all(prop == {"type": "boolean"} for prop in answer_schema["properties"].values())
            assert "uniqueItems" not in json.dumps(answer_schema, ensure_ascii=False)
        elif row["response_schema"]["allowed_answer_values"]:
            answer_schema = schema["properties"]["answer"]
            assert answer_schema["type"] == "string"
            assert answer_schema["enum"] == row["response_schema"]["allowed_answer_values"]
        elif row["answer_type"] == "identifier":
            answer_schema = schema["properties"]["answer"]
            assert answer_schema["type"] == "string"
            assert "enum" not in answer_schema
        elif row["answer_type"] == "status":
            assert "enum" not in schema["properties"]["answer"]
            assert row["response_schema"]["allowed_answer_values"] == []
        elif row["answer_type"] in {"money", "integer", "threshold", "date", "date_range", "datetime"}:
            assert "enum" not in json.dumps(schema["properties"]["answer"], ensure_ascii=False)


def test_codex_provider_nonzero_exit_raises_and_run_model_records_error(tmp_path: Path):
    import rudocground.providers.codex_cli_provider as codex_module

    class FakeTempDir:
        def __init__(self, path: Path) -> None:
            self.name = str(path)

        def __enter__(self):
            Path(self.name).mkdir(parents=True, exist_ok=True)
            return self.name

        def __exit__(self, exc_type, exc, tb):
            return False

    def tempdir_factory():
        return FakeTempDir(tmp_path / "td")

    def fake_run(cmd, input, text, capture_output, cwd):
        return subprocess.CompletedProcess(cmd, 1, stdout='{"type":"error"}\n', stderr="boom")

    provider = CodexCliProvider(model="codex-default", client_runner=fake_run, tempdir_factory=tempdir_factory, codex_version_override="codex-cli test")
    task = PromptTask(
        case_id="trip_001",
        variant_id="A",
        question_id="Q6",
        prompt="prompt",
        system_prompt="sys",
        response_schema={
            "case_id": "trip_001",
            "variant_id": "A",
            "question_id": "Q6",
            "answer": None,
            "decision": None,
            "evidence": [],
            "evidence_details": [],
            "missing_information": [],
            "explanation": "",
        },
    )
    with pytest.raises(RuntimeError):
        provider.generate(task)

    output = tmp_path / "codex-error.jsonl"
    run_model(
        "prompts/trip_001_all.jsonl",
        "codex",
        "codex-default",
        output,
        provider=provider,
        limit=1,
    )
    rows = _read_jsonl(output)
    assert rows[0]["status"] == "error"


def test_codex_provider_resume_skips_ok_and_retries_error(tmp_path: Path):
    calls = []

    class FakeTempDir:
        def __init__(self, path: Path) -> None:
            self.name = str(path)

        def __enter__(self):
            Path(self.name).mkdir(parents=True, exist_ok=True)
            return self.name

        def __exit__(self, exc_type, exc, tb):
            return False

    def tempdir_factory():
        return FakeTempDir(tmp_path / f"td-{len(calls)+1}")

    def fake_run_error(cmd, input, text, capture_output, cwd):
        calls.append((cwd, input))
        return subprocess.CompletedProcess(cmd, 1, stdout='{"type":"error"}\n', stderr="boom")

    def fake_run_ok(cmd, input, text, capture_output, cwd):
        calls.append((cwd, input))
        response_file = Path(cmd[cmd.index("-o") + 1])
        response_file.write_text(
            json.dumps(
                {
                    "answer": "45 600,00 руб.",
                    "decision": "reimburse",
                    "evidence": ["policy_01#appendix_1"],
                    "evidence_details": [],
                    "missing_information": [],
                    "explanation": "",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout='{"type":"turn.completed"}\n', stderr="")

    provider = CodexCliProvider(model="codex-default", client_runner=fake_run_error, tempdir_factory=tempdir_factory, codex_version_override="codex-cli test")
    output = tmp_path / "codex.jsonl"
    run_model(
        "prompts/trip_001_all.jsonl",
        "codex",
        "codex-default",
        output,
        provider=provider,
        limit=1,
    )
    assert len(calls) == 1
    rows = _read_jsonl(output)
    assert rows[0]["status"] == "error"

    provider_ok = CodexCliProvider(model="codex-default", client_runner=fake_run_ok, tempdir_factory=tempdir_factory, codex_version_override="codex-cli test")
    run_model(
        "prompts/trip_001_all.jsonl",
        "codex",
        "codex-default",
        output,
        provider=provider_ok,
        limit=1,
        resume=True,
    )
    rows = _read_jsonl(output)
    assert rows[0]["status"] == "ok"
    assert len(calls) == 2
    assert len(rows) == 1


def test_codex_diagnostics_returns_summary(monkeypatch):
    import rudocground.providers.codex_cli_provider as codex_module

    monkeypatch.setattr(codex_module, "_codex_version", lambda codex_binary=None: "codex-cli test")
    monkeypatch.setattr(
        codex_module,
        "_doctor_report",
        lambda codex_binary=None: {
            "available": True,
            "auth": True,
            "doctor": {},
            "resolved_binary_path": "/resolved/codex",
            "checked_binary_paths": ["/resolved/codex"],
        },
    )

    class FakeProvider:
        def __init__(self, *args, **kwargs):
            pass

        def generate(self, task):
            return ModelPrediction(
                case_id=task.case_id,
                variant_id=task.variant_id,
                question_id=task.question_id,
                answer=1,
                decision=None,
                evidence=[],
                evidence_details=[],
                missing_information=[],
                explanation="",
                status="ok",
                provider="codex_cli",
                model="codex-default",
                raw_response={"ok": True},
                codex_cli_version="codex-cli test",
            )

    monkeypatch.setattr(codex_module, "CodexCliProvider", FakeProvider)
    report = codex_diagnostics("/custom/codex")
    assert report["codex_found"] is True
    assert report["authorized"] is True
    assert report["smoke_test_ok"] is True
    assert report["resolved_binary_path"] == "/resolved/codex"


def test_codex_binary_resolves_from_env(monkeypatch, tmp_path: Path):
    import rudocground.providers.codex_cli_provider as codex_module

    binary = tmp_path / "codex-env"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("RUDOCGROUND_CODEX_BINARY", str(binary))
    monkeypatch.setattr(codex_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(codex_module, "_npm_global_prefix", lambda: None)
    provider = CodexCliProvider(model="codex-default")
    assert provider.resolved_binary_path == str(binary.resolve())


def test_codex_binary_resolves_from_shutil_which(monkeypatch, tmp_path: Path):
    import rudocground.providers.codex_cli_provider as codex_module

    binary = tmp_path / "codex-which"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.delenv("RUDOCGROUND_CODEX_BINARY", raising=False)
    monkeypatch.setattr(codex_module.shutil, "which", lambda name: str(binary) if name == "codex" else None)
    monkeypatch.setattr(codex_module, "_npm_global_prefix", lambda: None)
    provider = CodexCliProvider(model="codex-default")
    assert provider.resolved_binary_path == str(binary.resolve())


def test_codex_binary_falls_back_to_homebrew_path(monkeypatch):
    import rudocground.providers.codex_cli_provider as codex_module

    monkeypatch.delenv("RUDOCGROUND_CODEX_BINARY", raising=False)
    monkeypatch.setattr(codex_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(codex_module, "_npm_global_prefix", lambda: None)

    def fake_is_executable(path: Path) -> bool:
        return str(path.resolve()) == "/opt/homebrew/bin/codex"

    monkeypatch.setattr(codex_module, "_is_executable_file", fake_is_executable)
    provider = CodexCliProvider(model="codex-default")
    assert provider.resolved_binary_path == "/opt/homebrew/bin/codex"


def test_codex_binary_missing_raises_helpful_error(monkeypatch):
    import rudocground.providers.codex_cli_provider as codex_module

    monkeypatch.delenv("RUDOCGROUND_CODEX_BINARY", raising=False)
    monkeypatch.setattr(codex_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(codex_module, "_npm_global_prefix", lambda: None)
    monkeypatch.setattr(codex_module, "_is_executable_file", lambda path: False)

    with pytest.raises(RuntimeError) as excinfo:
        CodexCliProvider(model="codex-default")
    message = str(excinfo.value)
    assert "RUDOCGROUND_CODEX_BINARY" in message
    assert "PATH=" in message
    assert "checked_paths=" in message
