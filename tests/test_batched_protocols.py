from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

from rudocground.models import PromptTask
from rudocground.runners.batched import BatchSpec
from rudocground.runners.protocols.compact import CompactBatchedProtocol


def test_compact_decoder_does_not_copy_gold_missing_information() -> None:
    protocol = CompactBatchedProtocol()
    task = PromptTask(case_id="case_001", variant_id="A", question_id="Q1", answer_type="boolean", decision_required=False, prompt="Context:\n[DOCUMENT doc_id=policy] text\n\nQuestion:\nEnough?", response_schema={"answer_type": "boolean"})
    batch = BatchSpec(case_id="case_001", variant_id="A", label="compact", strategy=protocol.name, tasks=[task], prompt="prompt", schema={}, estimated_tokens=10, num_ctx=4096, num_predict=512, metadata={"index_to_doc": {"D0": "policy"}})
    rows = protocol.decode_response(batch=batch, parsed={"Q1": {"a": True, "d": None, "e": ["D0"], "m": True}}, provider=SimpleNamespace(model="test-model"), request_body={}, response_body={}, latency_ms=1, batch_response_path="batch.json")
    assert rows[0]["missing_information"] == []
    assert rows[0]["missing_information_detected"] is True
    assert rows[0]["missing_information_contract"] == "detection_only"
    assert rows[0]["evidence"] == ["policy"]


def test_compact_report_uses_detection_metric(tmp_path: Path) -> None:
    gold_path = tmp_path / "gold.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"
    gold_rows = [
        {"case_id": "case_001", "variant_id": "A", "question_id": "Q1", "answer_type": "boolean", "answer_normalized": True, "decision": "not_graded", "decision_required": False, "required_evidence": [], "supporting_evidence": [], "missing_information": ["approval"], "must_change_from_other_variant": False},
        {"case_id": "case_001", "variant_id": "A", "question_id": "Q2", "answer_type": "boolean", "answer_normalized": False, "decision": "not_graded", "decision_required": False, "required_evidence": [], "supporting_evidence": [], "missing_information": [], "must_change_from_other_variant": False},
    ]
    predictions = [
        {"case_id": "case_001", "variant_id": "A", "question_id": "Q1", "status": "ok", "missing_information_detected": True},
        {"case_id": "case_001", "variant_id": "A", "question_id": "Q2", "status": "ok", "missing_information_detected": False},
    ]
    gold_path.write_text("".join(json.dumps(row) + "\n" for row in gold_rows), encoding="utf-8")
    predictions_path.write_text("".join(json.dumps(row) + "\n" for row in predictions), encoding="utf-8")
    report = {"overall": {"missing_information_accuracy": 1.0}, "by_answer_type": {"boolean": {"missing_information_accuracy": 1.0}}, "variant_metrics": {"A": {"missing_information_accuracy": 1.0}}, "records": [{"key": {"case_id": "case_001", "variant_id": "A", "question_id": "Q1"}, "missing_information_correct": False}, {"key": {"case_id": "case_001", "variant_id": "A", "question_id": "Q2"}, "missing_information_correct": True}], "counterfactual": {}}
    result = protocol.postprocess_report(report, gold_path=gold_path, predictions_path=predictions_path)
    assert result["overall"]["missing_information_accuracy"] is None
    assert result["overall"]["missing_information_detection_accuracy"] == 1.0
    assert result["records"][0]["missing_information_correct"] is None
    assert result["records"][0]["missing_information_detection_correct"] is True
