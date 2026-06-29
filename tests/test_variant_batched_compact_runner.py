from __future__ import annotations

from rudocground.models import PromptTask
from rudocground.providers.ollama_provider import OllamaProvider
from rudocground.variant_batched_compact_runner import (
    _build_compact_prompt,
    _compact_row_schema,
    _flatten_batch_response,
)


def test_compact_prompt_uses_short_document_map():
    task = PromptTask(
        case_id="case_001",
        variant_id="A",
        question_id="Q1",
        answer_type="boolean",
        decision_required=True,
        prompt="Context: [DOCUMENT doc_id=doc_a] text [/DOCUMENT] Question: Is it approved?",
        system_prompt=None,
        response_schema={
            "answer_type": "boolean",
            "decision_required": True,
            "allowed_decision_labels": ["ok", "not_ok"],
            "allowed_answer_values": [],
            "allowed_code_values": [],
        },
    )
    prompt = _build_compact_prompt(
        case_id="case_001",
        variant_id="A",
        context="[DOCUMENT doc_idx=D0] text [/DOCUMENT]",
        batch_tasks=[task],
        question_texts={task.key(): "Is it approved?"},
        index_to_doc={"D0": "doc_a", "D1": "doc_b"},
    )
    schema = _compact_row_schema(task, ["D0", "D1"])
    assert '"D0": "doc_a"' in prompt
    assert '"D1": "doc_b"' in prompt
    assert "doc_id=doc_a" not in prompt
    assert schema["properties"]["a"]["type"] == "boolean"
    assert schema["properties"]["e"]["items"]["enum"] == ["D0", "D1"]


def test_compact_flatten_maps_evidence_indices_and_missing_information():
    task = PromptTask(
        case_id="case_001",
        variant_id="A",
        question_id="Q1",
        answer_type="categorical",
        decision_required=False,
        prompt="Context: docs. Question: Which source?",
        system_prompt=None,
        response_schema={
            "answer_type": "categorical",
            "decision_required": False,
            "allowed_decision_labels": [],
            "allowed_answer_values": ["accepted", "rejected"],
            "allowed_code_values": [],
        },
    )
    batch = {
        "case_id": "case_001",
        "variant_id": "A",
        "batch_label": "compact",
        "batch_strategy": "variant_batched_compact",
        "question_ids": ["Q1"],
        "tasks": [task],
        "doc_to_index": {"doc_a": "D0", "doc_b": "D1"},
        "index_to_doc": {"D0": "doc_a", "D1": "doc_b"},
    }
    parsed = {
        "Q1": {
            "a": "accepted",
            "d": None,
            "e": ["D1"],
            "m": True,
        }
    }
    rows = _flatten_batch_response(
        batch=batch,
        parsed=parsed,
        provider=OllamaProvider(model="qwen3:8b"),
        request_body={"model": "qwen3:8b"},
        response_body={"prompt_eval_count": 7, "eval_count": 5},
        latency_ms=12,
        gold_missing={("case_001", "A", "Q1"): ["source_document"]},
        batch_response_path="/tmp/batch.json",
    )
    assert rows[0]["evidence"] == ["doc_b"]
    assert rows[0]["missing_information"] == ["source_document"]
    assert rows[0]["answer"] == "accepted"
    assert rows[0]["decision"] is None
