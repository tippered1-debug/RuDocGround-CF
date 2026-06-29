from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

import pytest

from rudocground.models import PromptTask
from rudocground.providers.ollama_provider import OllamaProvider


@dataclass
class _FakeResponse:
    body: str

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body.encode("utf-8")


def test_ollama_provider_builds_structured_chat_request(monkeypatch):
    seen = {}

    def fake_run(cmd, check=False, capture_output=False, text=False):
        assert cmd == ["ollama", "list"]
        return subprocess.CompletedProcess(cmd, 0, stdout="NAME\nqwen3:8b\n", stderr="")

    def fake_opener(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        payload = {
            "model": "qwen3:8b",
            "message": {"role": "assistant", "content": "{\"answer\": true, \"decision\": \"ok\", \"evidence\": [], \"evidence_details\": [], \"missing_information\": [], \"explanation\": \"\"}"},
            "prompt_eval_count": 11,
            "eval_count": 7,
        }
        return _FakeResponse(json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr("rudocground.providers.ollama_provider.subprocess.run", fake_run)
    provider = OllamaProvider(model="qwen3:8b", opener=fake_opener, num_ctx=16384, temperature=0, seed=42, think=False)
    task = PromptTask(
        case_id="case_001",
        variant_id="A",
        question_id="Q1",
        answer_type="boolean",
        decision_required=True,
        prompt="Context: [DOCUMENT doc_id=doc_1] text [/DOCUMENT] Question: Is it approved?",
        system_prompt="Use only the documents.",
        response_schema={
            "case_id": "case_001",
            "variant_id": "A",
            "question_id": "Q1",
            "answer": None,
            "decision": None,
            "evidence": [],
            "evidence_details": [],
            "missing_information": [],
            "explanation": "",
            "answer_type": "boolean",
            "decision_required": True,
            "allowed_decision_labels": ["ok", "not_ok"],
            "allowed_answer_values": [],
            "allowed_code_values": [],
        },
    )
    prediction = provider.generate(task)
    assert prediction.answer is True
    assert prediction.decision == "ok"
    assert seen["url"] == "http://127.0.0.1:11434/api/chat"
    assert seen["body"]["stream"] is False
    assert seen["body"]["think"] is False
    assert seen["body"]["keep_alive"] == "30m"
    assert seen["body"]["options"]["temperature"] == 0
    assert seen["body"]["options"]["seed"] == 42
    assert seen["body"]["options"]["num_ctx"] == 16384
    assert seen["body"]["options"]["num_predict"] == 1024
    assert seen["body"]["format"]["properties"]["answer"]["type"] == "boolean"
    assert seen["body"]["messages"][0]["role"] == "system"
    assert seen["body"]["messages"][1]["role"] == "user"


def test_ollama_provider_expands_pipe_joined_code_set_into_boolean_object(monkeypatch):
    def fake_run(cmd, check=False, capture_output=False, text=False):
        assert cmd == ["ollama", "list"]
        return subprocess.CompletedProcess(cmd, 0, stdout="NAME\nqwen3:8b\n", stderr="")

    def fake_opener(request, timeout):
        payload = {
            "model": "qwen3:8b",
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "answer": {"build_scripts": True, "source_code_archive": False},
                        "decision": "build_scripts|source_code_archive",
                        "evidence": [],
                        "evidence_details": [],
                        "missing_information": [],
                        "explanation": "",
                    },
                    ensure_ascii=False,
                ),
            },
            "prompt_eval_count": 9,
            "eval_count": 6,
        }
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(json.dumps(payload, ensure_ascii=False))

    seen = {}
    monkeypatch.setattr("rudocground.providers.ollama_provider.subprocess.run", fake_run)
    provider = OllamaProvider(model="qwen3:8b", opener=fake_opener)
    task = PromptTask(
        case_id="iplic_016",
        variant_id="A",
        question_id="Q5",
        answer_type="code_set",
        decision_required=True,
        prompt="Context: [DOCUMENT doc_id=doc_1] text [/DOCUMENT] Question: Which codes apply?",
        system_prompt="Use only the documents.",
        response_schema={
            "case_id": "iplic_016",
            "variant_id": "A",
            "question_id": "Q5",
            "answer": None,
            "decision": None,
            "evidence": [],
            "missing_information": [],
            "explanation": "",
            "answer_type": "code_set",
            "decision_required": True,
            "allowed_decision_labels": ["not_build_scripts|source_code_archive", "build_scripts|source_code_archive"],
            "allowed_answer_values": [],
            "allowed_code_values": ["build_scripts|source_code_archive"],
        },
    )
    prediction = provider.generate(task)
    assert prediction.answer == ["build_scripts"]
    assert seen["body"]["format"]["properties"]["answer"]["type"] == "object"
    assert list(seen["body"]["format"]["properties"]["answer"]["properties"].keys()) == [
        "build_scripts",
        "source_code_archive",
    ]
    assert seen["body"]["format"]["properties"]["answer"]["required"] == [
        "build_scripts",
        "source_code_archive",
    ]


def test_ollama_provider_diagnostics_reports_model_presence(monkeypatch):
    def fake_run(cmd, check=False, capture_output=False, text=False):
        if cmd == ["ollama", "list"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="NAME\nqwen3:8b\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    def fake_opener(request, timeout):
        payload = {
            "model": "qwen3:8b",
            "message": {"role": "assistant", "content": "{\"answer\": \"да\"}"},
            "prompt_eval_count": 3,
            "eval_count": 2,
        }
        return _FakeResponse(json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr("rudocground.providers.ollama_provider.subprocess.run", fake_run)
    provider = OllamaProvider(model="qwen3:8b", opener=fake_opener)
    report = provider.diagnostics()
    assert report["model_present"] is True
    assert report["api_available"] is True
