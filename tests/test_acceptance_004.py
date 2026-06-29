from __future__ import annotations

import json
import shutil
from pathlib import Path

from rudocground.case_tools import audit_case, audit_source_fidelity, prepare_prompts
from rudocground.io import load_gold


CASE_DIR = Path("data/cases/acceptance_004")
SOURCE_DIR = Path("data/source_documents/acceptance_004")
GOLD_PATH = Path("data/gold.jsonl")


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _copy_acceptance_case(tmp_path: Path) -> Path:
    target = tmp_path / "acceptance_004_case"
    shutil.copytree(CASE_DIR, target)
    return target


def _copy_acceptance_sources(tmp_path: Path) -> Path:
    target = tmp_path / "acceptance_004_sources"
    shutil.copytree(SOURCE_DIR, target)
    return target


def _hash_map_any(directory: Path) -> dict[str, str]:
    import hashlib

    hashes: dict[str, str] = {}
    for file_path in sorted(directory.iterdir()):
        if file_path.is_file():
            hashes[file_path.name] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return hashes


def test_acceptance_case_has_seven_documents_and_prompts(tmp_path: Path):
    case_copy = _copy_acceptance_case(tmp_path)
    source_copy = _copy_acceptance_sources(tmp_path)
    output_dir = tmp_path / "acceptance_prompts"

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
    assert differing == ["05_Акт_сдачи-приёмки.txt"]

    act_a = (case_copy / "A" / "documents" / "05_Акт_сдачи-приёмки.txt").read_text(encoding="utf-8")
    act_b = (case_copy / "B" / "documents" / "05_Акт_сдачи-приёмки.txt").read_text(encoding="utf-8")
    assert act_a != act_b
    assert (
        act_a.replace("Подпись заказчика: __________ /Кузнецов Илья Андреевич/", "Подпись заказчика:")
        .replace("Отметка о подписании: Акт подписан обеими сторонами.", "Отметка о подписании:")
        == act_b
    )

    counts = prepare_prompts(case_copy, GOLD_PATH, output_dir)
    assert counts == {"A": 16, "B": 16, "all": 32}
    assert len(_read_jsonl(output_dir / "acceptance_004_A.jsonl")) == 16
    assert len(_read_jsonl(output_dir / "acceptance_004_B.jsonl")) == 16
    assert len(_read_jsonl(output_dir / "acceptance_004_all.jsonl")) == 32

    prompt_a_rows = _read_jsonl(output_dir / "acceptance_004_A.jsonl")
    prompt_b_rows = _read_jsonl(output_dir / "acceptance_004_B.jsonl")
    prompt_all_rows = _read_jsonl(output_dir / "acceptance_004_all.jsonl")
    keys_all = {(row["case_id"], row["variant_id"], row["question_id"]) for row in prompt_all_rows}
    assert len(keys_all) == 32
    assert len({row["question_id"] for row in prompt_all_rows}) == 16

    prompt_a = prompt_a_rows[0]["prompt"]
    prompt_b = prompt_b_rows[0]["prompt"]
    prompt_head = prompt_a.split("Context:", 1)[0]
    assert "[DOCUMENT doc_id=acceptance_act_A]" in prompt_a
    assert "[DOCUMENT doc_id=acceptance_act_B]" not in prompt_a
    assert "[DOCUMENT doc_id=acceptance_act_B]" in prompt_b
    assert "[DOCUMENT doc_id=acceptance_act_A]" not in prompt_b
    assert "gold_status" not in prompt_head
    assert "required_evidence" not in prompt_head
    assert "must_change_from_other_variant" not in prompt_head
    assert "answer_normalized" not in prompt_head


def test_acceptance_gold_rows_cover_required_counts_and_decisions():
    gold = load_gold(GOLD_PATH)
    acceptance_rows = [row for row in gold.records if row.case_id == "acceptance_004"]
    assert len(acceptance_rows) == 32

    by_qid: dict[str, dict[str, object]] = {}
    for row in acceptance_rows:
        by_qid.setdefault(row.question_id, {})[row.variant_id] = row

    assert by_qid["Q1"]["A"].answer_type == "status"
    assert by_qid["Q1"]["B"].answer_type == "status"
    assert by_qid["Q1"]["A"].answer_normalized == "ООО «ПроектЛаб»"
    assert by_qid["Q3"]["A"].answer_type == "status"
    assert by_qid["Q3"]["A"].answer_normalized == "network_infrastructure_assessment_and_technical_report"
    assert by_qid["Q5"]["A"].decision == "substantive_comments_not_recorded"
    assert by_qid["Q5"]["B"].decision == "substantive_comments_not_recorded"
    assert by_qid["Q9"]["A"].rationale == "Счёт содержит сумму и назначение платежа, но не подтверждает подписание акта заказчиком."
    assert by_qid["Q9"]["B"].rationale == "Счёт содержит сумму и назначение платежа, но не подтверждает подписание акта заказчиком."
    assert by_qid["Q12"]["A"].required_evidence == ["project_correspondence#no_comments", "acceptance_act_A#signed_by_both"]
    assert by_qid["Q12"]["B"].required_evidence == ["project_correspondence#no_comments", "acceptance_act_B#customer_signature_blank"]
    assert by_qid["Q13"]["A"].required_evidence == ["service_contract#acceptance_clause", "acceptance_act_A#signed_by_both"]
    assert by_qid["Q13"]["B"].required_evidence == ["service_contract#acceptance_clause", "acceptance_act_B#customer_signature_blank"]
    assert by_qid["Q11"]["A"].decision_required is False
    assert by_qid["Q11"]["B"].decision_required is False
    assert by_qid["Q15"]["A"].question == "Присутствует ли подпись заказчика на акте, включённом в комплект документов для оплаты?"
    assert by_qid["Q15"]["B"].question == "Присутствует ли подпись заказчика на акте, включённом в комплект документов для оплаты?"
    assert by_qid["Q15"]["A"].decision == "customer_signature_present_in_payment_package"
    assert by_qid["Q15"]["B"].decision == "customer_signature_missing_in_payment_package"

    flip_questions = {row.question_id for row in acceptance_rows if row.must_change_from_other_variant}
    assert flip_questions == {"Q6", "Q7", "Q8", "Q14", "Q15", "Q16"}
    invariant_questions = {row.question_id for row in acceptance_rows if not row.must_change_from_other_variant}
    assert invariant_questions == {"Q1", "Q2", "Q3", "Q4", "Q5", "Q9", "Q10", "Q11", "Q12", "Q13"}


def test_acceptance_has_no_cross_variant_evidence():
    gold = load_gold(GOLD_PATH)
    acceptance_rows = [row for row in gold.records if row.case_id == "acceptance_004"]

    for row in acceptance_rows:
        evidence_items = list(row.required_evidence) + list(row.supporting_evidence)
        if row.variant_id == "A":
            assert all("acceptance_act_B" not in item for item in evidence_items)
        else:
            assert all("acceptance_act_A" not in item for item in evidence_items)
