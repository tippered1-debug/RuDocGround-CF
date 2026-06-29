from __future__ import annotations

import json
import shutil
from pathlib import Path

from rudocground.case_tools import audit_case, audit_source_fidelity, prepare_prompts
from rudocground.io import load_gold


CASE_DIR = Path("data/cases/notice_005")
SOURCE_DIR = Path("data/source_documents/notice_005")
GOLD_PATH = Path("data/gold.jsonl")


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _copy_notice_case(tmp_path: Path) -> Path:
    target = tmp_path / "notice_005_case"
    shutil.copytree(CASE_DIR, target)
    return target


def _copy_notice_sources(tmp_path: Path) -> Path:
    target = tmp_path / "notice_005_sources"
    shutil.copytree(SOURCE_DIR, target)
    return target


def _hash_map_any(directory: Path) -> dict[str, str]:
    import hashlib

    hashes: dict[str, str] = {}
    for file_path in sorted(directory.iterdir()):
        if file_path.is_file():
            hashes[file_path.name] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return hashes


def test_notice_case_has_seven_documents_and_prompts(tmp_path: Path):
    case_copy = _copy_notice_case(tmp_path)
    source_copy = _copy_notice_sources(tmp_path)
    output_dir = tmp_path / "notice_prompts"

    summary = audit_case(case_copy)
    assert summary is None
    source_summary = audit_source_fidelity(case_copy, source_copy)
    assert source_summary["documents_in_a"] == 7
    assert source_summary["documents_in_b"] == 7
    assert source_summary["source_files"] == 8

    hashes_a = _hash_map_any(case_copy / "A" / "documents")
    hashes_b = _hash_map_any(case_copy / "B" / "documents")
    assert len(hashes_a) == len(hashes_b) == 7
    differing = [name for name in hashes_a if hashes_a[name] != hashes_b[name]]
    assert differing == ["03_Подтверждение_доставки.txt"]

    confirmation_a = (case_copy / "A" / "documents" / "03_Подтверждение_доставки.txt").read_text(encoding="utf-8")
    confirmation_b = (case_copy / "B" / "documents" / "03_Подтверждение_доставки.txt").read_text(encoding="utf-8")
    assert confirmation_a != confirmation_b
    assert confirmation_a.replace("19 октября 2026 г.", "22 октября 2026 г.") == confirmation_b

    counts = prepare_prompts(case_copy, GOLD_PATH, output_dir)
    assert counts == {"A": 16, "B": 16, "all": 32}
    assert len(_read_jsonl(output_dir / "notice_005_A.jsonl")) == 16
    assert len(_read_jsonl(output_dir / "notice_005_B.jsonl")) == 16
    assert len(_read_jsonl(output_dir / "notice_005_all.jsonl")) == 32

    prompt_a_rows = _read_jsonl(output_dir / "notice_005_A.jsonl")
    prompt_b_rows = _read_jsonl(output_dir / "notice_005_B.jsonl")
    prompt_all_rows = _read_jsonl(output_dir / "notice_005_all.jsonl")
    assert len({(row["case_id"], row["variant_id"], row["question_id"]) for row in prompt_all_rows}) == 32
    assert len({row["question_id"] for row in prompt_all_rows}) == 16
    assert "[DOCUMENT doc_id=delivery_confirmation_A]" in prompt_a_rows[0]["prompt"]
    assert "[DOCUMENT doc_id=delivery_confirmation_B]" in prompt_b_rows[0]["prompt"]


def test_notice_gold_rows_cover_required_counts_and_decisions():
    gold = load_gold(GOLD_PATH)
    notice_rows = [row for row in gold.records if row.case_id == "notice_005"]
    assert len(notice_rows) == 32
    assert {row.variant_id for row in notice_rows} == {"A", "B"}
    assert {row.question_id for row in notice_rows} == {f"Q{i}" for i in range(1, 17)}

    by_qid: dict[str, dict[str, object]] = {}
    for row in notice_rows:
        by_qid.setdefault(row.question_id, {})[row.variant_id] = row

    assert by_qid["Q1"]["A"].answer_type == "status"
    assert by_qid["Q1"]["A"].answer_normalized == "ООО «ОблакоСервис»"
    assert by_qid["Q4"]["A"].question == "Какой датой оформлено уведомление об отказе от продления?"
    assert by_qid["Q4"]["A"].answer_type == "date"
    assert by_qid["Q4"]["A"].answer_normalized == "2026-10-18"
    assert by_qid["Q4"]["A"].decision == "notice_dated_2026_10_18"
    assert by_qid["Q4"]["B"].decision == "notice_dated_2026_10_18"
    assert by_qid["Q4"]["A"].decision_required is False
    assert by_qid["Q5"]["A"].decision_required is True
    assert by_qid["Q5"]["B"].decision_required is True
    assert by_qid["Q5"]["A"].required_evidence == [
        "dispatch_email#18 октября 2026 г.",
        "service_contract#не позднее 20 октября 2026 г. включительно",
    ]
    assert by_qid["Q8"]["A"].required_evidence == [
        "service_contract#автоматически продлевается на один год",
        "service_contract#дата получения уведомления исполнителем",
        "delivery_confirmation_A#19 октября 2026 г.",
        "service_contract#подлежат оплате на основании счёта",
        "november_invoice#на услуги управляемого резервного копирования за ноябрь 2026 г.",
    ]
    assert by_qid["Q8"]["B"].required_evidence == [
        "service_contract#автоматически продлевается на один год",
        "service_contract#дата получения уведомления исполнителем",
        "delivery_confirmation_B#22 октября 2026 г.",
        "service_contract#подлежат оплате на основании счёта",
        "november_invoice#на услуги управляемого резервного копирования за ноябрь 2026 г.",
    ]
    assert by_qid["Q15"]["A"].required_evidence == [
        "service_contract#по 31 октября 2026 г. включительно",
        "service_contract#автоматически продлевается на один год",
        "service_contract#не позднее 20 октября 2026 г. включительно",
        "delivery_confirmation_A#19 октября 2026 г.",
        "service_contract#подлежат оплате на основании счёта",
        "november_invoice#на услуги управляемого резервного копирования за ноябрь 2026 г.",
    ]
    assert by_qid["Q15"]["B"].required_evidence == [
        "service_contract#по 31 октября 2026 г. включительно",
        "service_contract#автоматически продлевается на один год",
        "service_contract#не позднее 20 октября 2026 г. включительно",
        "delivery_confirmation_B#22 октября 2026 г.",
        "service_contract#подлежат оплате на основании счёта",
        "november_invoice#на услуги управляемого резервного копирования за ноябрь 2026 г.",
    ]
    assert by_qid["Q16"]["A"].required_evidence == [
        "service_contract#по 31 октября 2026 г. включительно",
        "service_contract#автоматически продлевается на один год",
        "service_contract#дата получения уведомления исполнителем",
        "delivery_confirmation_A#19 октября 2026 г.",
    ]
    assert by_qid["Q16"]["B"].required_evidence == [
        "service_contract#по 31 октября 2026 г. включительно",
        "service_contract#автоматически продлевается на один год",
        "service_contract#дата получения уведомления исполнителем",
        "delivery_confirmation_B#22 октября 2026 г.",
    ]
    assert by_qid["Q16"]["A"].decision == "contract_not_active_in_november"
    assert by_qid["Q16"]["B"].decision == "contract_active_in_november"

    flip_questions = {row.question_id for row in notice_rows if row.must_change_from_other_variant}
    assert flip_questions == {"Q6", "Q7", "Q8", "Q13", "Q15", "Q16"}
    invariant_questions = {row.question_id for row in notice_rows if not row.must_change_from_other_variant}
    assert invariant_questions == {"Q1", "Q2", "Q3", "Q4", "Q5", "Q9", "Q10", "Q11", "Q12", "Q14"}

    assert all(
        not (row.question_id in {"Q15", "Q16"} and row.answer_normalized is True and row.variant_id == "A")
        for row in notice_rows
    )


def test_notice_has_no_cross_variant_evidence():
    gold = load_gold(GOLD_PATH)
    notice_rows = [row for row in gold.records if row.case_id == "notice_005"]

    for row in notice_rows:
        evidence_items = list(row.required_evidence) + list(row.supporting_evidence)
        if row.variant_id == "A":
            assert all("delivery_confirmation_B" not in item for item in evidence_items)
        else:
            assert all("delivery_confirmation_A" not in item for item in evidence_items)
