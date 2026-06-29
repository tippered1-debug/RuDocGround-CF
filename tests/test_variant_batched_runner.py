from __future__ import annotations

from rudocground.models import PromptTask
from rudocground.variant_batched_runner import _answer_schema, _batch_schema, _build_batch_prompt


def test_variant_batch_schema_contains_all_question_keys():
    tasks = [
        PromptTask(
            case_id="case_001",
            variant_id="A",
            question_id="Q1",
            answer_type="boolean",
            decision_required=True,
            prompt="Context: docs. Question: Q1?",
            system_prompt=None,
            response_schema={
                "answer_type": "boolean",
                "decision_required": True,
                "allowed_decision_labels": ["yes", "no"],
                "allowed_answer_values": [],
                "allowed_code_values": [],
            },
        ),
        PromptTask(
            case_id="case_001",
            variant_id="A",
            question_id="Q2",
            answer_type="code_set",
            decision_required=False,
            prompt="Context: docs. Question: Q2?",
            system_prompt=None,
            response_schema={
                "answer_type": "code_set",
                "decision_required": False,
                "allowed_decision_labels": [],
                "allowed_answer_values": [],
                "allowed_code_values": ["code_a", "code_b"],
            },
        ),
    ]
    schema = _batch_schema(tasks)
    assert schema["required"] == ["Q1", "Q2"]
    assert schema["properties"]["Q1"]["properties"]["answer"]["type"] == "boolean"
    assert schema["properties"]["Q2"]["properties"]["answer"]["type"] == "array"
    assert schema["properties"]["Q2"]["properties"]["answer"]["items"]["enum"] == ["code_a", "code_b"]


def test_variant_batch_prompt_mentions_canonical_answer_contract():
    task = PromptTask(
        case_id="case_001",
        variant_id="A",
        question_id="Q1",
        answer_type="code_set",
        decision_required=True,
        prompt="Context: [DOCUMENT doc_id=doc_1] text [/DOCUMENT] Question: What codes apply?",
        system_prompt=None,
        response_schema={
            "answer_type": "code_set",
            "decision_required": True,
            "allowed_decision_labels": ["yes", "no"],
            "allowed_answer_values": [],
            "allowed_code_values": ["build_scripts", "source_code_archive"],
        },
    )
    prompt = _build_batch_prompt(
        "case_001",
        "A",
        "[DOCUMENT doc_id=doc_1] text [/DOCUMENT]",
        [task],
        {"Q1": "What codes apply?"},
    )
    assert "Q1" in prompt
    assert "canonical codes" in prompt
    assert "answer_type=code_set" in prompt

