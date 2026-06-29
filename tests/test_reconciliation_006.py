from __future__ import annotations

import json
import shutil
from pathlib import Path

from rudocground.case_tools import audit_case, audit_source_fidelity, prepare_prompts
from rudocground.io import load_gold


CASE_DIR = Path("data/cases/reconciliation_006")
SOURCE_DIR = Path("data/source_documents/reconciliation_006")
GOLD_PATH = Path("data/gold.jsonl")


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _copy_case(tmp_path: Path) -> Path:
    target = tmp_path / "reconciliation_006_case"
    shutil.copytree(CASE_DIR, target)
    return target


def _copy_sources(tmp_path: Path) -> Path:
    target = tmp_path / "reconciliation_006_sources"
    shutil.copytree(SOURCE_DIR, target)
    return target


def _hash_map_any(directory: Path) -> dict[str, str]:
    import hashlib

    hashes: dict[str, str] = {}
    for file_path in sorted(directory.iterdir()):
        if file_path.is_file():
            hashes[file_path.name] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return hashes


def test_reconciliation_case_has_seven_documents_and_prompts(tmp_path: Path):
    case_copy = _copy_case(tmp_path)
    source_copy = _copy_sources(tmp_path)
    output_dir = tmp_path / "reconciliation_prompts"

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
    assert differing == ["06_Счёт_поставщика.txt"]

    invoice_a = (case_copy / "A" / "documents" / "06_Счёт_поставщика.txt").read_text(encoding="utf-8")
    invoice_b = (case_copy / "B" / "documents" / "06_Счёт_поставщика.txt").read_text(encoding="utf-8")
    assert "Цена за единицу: 32 000 руб." in invoice_a
    assert "Цена за единицу: 32 000 руб." in invoice_b
    assert invoice_a != invoice_b
    assert invoice_a.replace("Количество: 50 шт.", "Количество: 55 шт.").replace(
        "Сумма к оплате: 1 600 000 руб.",
        "Сумма к оплате: 1 760 000 руб.",
    ) == invoice_b

    counts = prepare_prompts(case_copy, GOLD_PATH, output_dir)
    assert counts == {"A": 16, "B": 16, "all": 32}
    assert len(_read_jsonl(output_dir / "reconciliation_006_A.jsonl")) == 16
    assert len(_read_jsonl(output_dir / "reconciliation_006_B.jsonl")) == 16
    assert len(_read_jsonl(output_dir / "reconciliation_006_all.jsonl")) == 32

    prompt_a_rows = _read_jsonl(output_dir / "reconciliation_006_A.jsonl")
    prompt_b_rows = _read_jsonl(output_dir / "reconciliation_006_B.jsonl")
    prompt_all_rows = _read_jsonl(output_dir / "reconciliation_006_all.jsonl")
    assert len({(row["case_id"], row["variant_id"], row["question_id"]) for row in prompt_all_rows}) == 32
    assert len({row["question_id"] for row in prompt_all_rows}) == 16

    prompt_a = prompt_a_rows[0]["prompt"]
    prompt_b = prompt_b_rows[0]["prompt"]
    prompt_head = prompt_a.split("Context:", 1)[0]
    assert "[DOCUMENT doc_id=payment_control_policy]" in prompt_a
    assert "[DOCUMENT doc_id=supplier_invoice_A]" in prompt_a
    assert "[DOCUMENT doc_id=supplier_invoice_B]" not in prompt_a
    assert "[DOCUMENT doc_id=supplier_invoice_B]" in prompt_b
    assert "[DOCUMENT doc_id=supplier_invoice_A]" not in prompt_b
    assert "gold_status" not in prompt_head
    assert "required_evidence" not in prompt_head
    assert "must_change_from_other_variant" not in prompt_head
    assert "answer_normalized" not in prompt_head


def test_reconciliation_gold_rows_cover_required_counts_and_decisions():
    gold = load_gold(GOLD_PATH)
    reconciliation_rows = [row for row in gold.records if row.case_id == "reconciliation_006"]
    assert len(reconciliation_rows) == 32
    assert {row.variant_id for row in reconciliation_rows} == {"A", "B"}
    assert {row.question_id for row in reconciliation_rows} == {f"Q{i}" for i in range(1, 17)}

    by_qid: dict[str, dict[str, object]] = {}
    for row in reconciliation_rows:
        by_qid.setdefault(row.question_id, {})[row.variant_id] = row

    assert by_qid["Q1"]["A"].answer_type == "status"
    assert by_qid["Q1"]["A"].answer_normalized == "ООО «СеверТех»"
    assert by_qid["Q3"]["A"].answer_type == "integer"
    assert by_qid["Q3"]["A"].answer_normalized == 50
    assert by_qid["Q5"]["A"].answer_type == "money"
    assert by_qid["Q5"]["A"].answer_normalized == 32000
    assert by_qid["Q6"]["A"].decision == "invoice_quantity_matches_order"
    assert by_qid["Q6"]["B"].decision == "invoice_quantity_does_not_match_order"
    assert by_qid["Q7"]["A"].decision == "invoice_total_matches_order_total"
    assert by_qid["Q7"]["B"].decision == "invoice_total_does_not_match_order_total"
    assert by_qid["Q12"]["A"].answer_type == "status"
    assert by_qid["Q12"]["A"].answer_normalized == "supplier_invoice"
    assert by_qid["Q13"]["A"].answer_type == "money"
    assert by_qid["Q13"]["A"].answer_normalized == 1600000
    assert by_qid["Q14"]["A"].decision == "documents_reconciled_for_payment"
    assert by_qid["Q14"]["B"].decision == "documents_not_reconciled_due_to_invoice_discrepancy"
    assert by_qid["Q15"]["A"].answer_normalized is False
    assert by_qid["Q15"]["B"].answer_normalized is True
    assert by_qid["Q16"]["A"].answer_normalized is True
    assert by_qid["Q16"]["B"].answer_normalized is False
    assert by_qid["Q4"]["A"].decision_required is True
    assert by_qid["Q4"]["B"].decision_required is True
    assert by_qid["Q11"]["A"].decision_required is True
    assert by_qid["Q11"]["B"].decision_required is True

    flip_questions = {row.question_id for row in reconciliation_rows if row.must_change_from_other_variant}
    assert flip_questions == {"Q6", "Q7", "Q8", "Q14", "Q15", "Q16"}
    invariant_questions = {row.question_id for row in reconciliation_rows if not row.must_change_from_other_variant}
    assert invariant_questions == {"Q1", "Q2", "Q3", "Q4", "Q5", "Q9", "Q10", "Q11", "Q12", "Q13"}


def test_reconciliation_has_no_cross_variant_evidence():
    gold = load_gold(GOLD_PATH)
    reconciliation_rows = [row for row in gold.records if row.case_id == "reconciliation_006"]

    for row in reconciliation_rows:
        evidence_items = list(row.required_evidence) + list(row.supporting_evidence)
        if row.variant_id == "A":
            assert all("supplier_invoice_B" not in item for item in evidence_items)
        else:
            assert all("supplier_invoice_A" not in item for item in evidence_items)
