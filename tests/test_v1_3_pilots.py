import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CASES = ["logistics_014", "iplic_016", "privacy_017", "hr_019", "procure_022"]


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case_id", CASES)
def test_case_documents_exist(case_id):
    case_root = ROOT / "data" / "cases" / case_id
    for variant in ["A", "B", "C"]:
        assert (case_root / variant / "context.json").exists()
        assert (case_root / variant / "context.txt").exists()
        assert (case_root / variant / "documents").is_dir()
    assert (case_root / "manifest.json").exists()
    assert (case_root / "question_matrix.md").exists()


@pytest.mark.parametrize("case_id", CASES)
def test_question_ids_align(case_id):
    lines = (ROOT / "data" / "cases" / case_id / "question_matrix.md").read_text(encoding="utf-8").splitlines()
    qids = [line.split("|")[1].strip() for line in lines[2:] if line.startswith("| Q")]
    assert len(qids) == 14
    assert sorted(qids, key=lambda q: int(q[1:])) == [f"Q{i}" for i in range(1, 15)]


def test_pilot_gold_row_count():
    rows = (ROOT / "data" / "v1_3_pilot_gold.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 210


def test_pilot_relation_counts():
    rel = _load(ROOT / "results" / "v1_3_pilot_relation_audit.json")
    assert rel["expected_change_pairs"] >= 15
    assert rel["expected_invariant_pairs"] >= 30


def test_preflight_docs_exist():
    assert (ROOT / "docs" / "v1_3_preflight_privacy_017.md").exists()
    assert (ROOT / "docs" / "v1_3_preflight_procure_022.md").exists()
