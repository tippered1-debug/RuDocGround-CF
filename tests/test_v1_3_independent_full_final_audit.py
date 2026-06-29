from __future__ import annotations

from pathlib import Path

import pytest

from rudocground.final_audit import build_full_audit


GOLD_PATH = Path("data/v1_3_full_gold.jsonl")
PREDICTIONS_PATH = Path("results/qwen3.5-4b_v1.3.1_independent_full_predictions.jsonl")
PROMPTS_PATH = Path("prompts/v1_3_full_prompts.jsonl")


@pytest.fixture(scope="module")
def audit() -> dict[str, object]:
    return build_full_audit(gold_path=GOLD_PATH, predictions_path=PREDICTIONS_PATH, prompts_path=PROMPTS_PATH)


def test_terminal_key_alignment_and_counts(audit: dict[str, object]) -> None:
    counts = audit["counts"]
    key_alignment = audit["key_alignment"]

    assert counts["gold_rows"] == 1160
    assert counts["prediction_rows"] == 2554
    assert counts["unique_prediction_keys"] == 1160
    assert counts["valid_rows"] == 921
    assert counts["format_failures"] == 239

    assert key_alignment["prompt_keys"] == 1160
    assert key_alignment["gold_keys"] == 1160
    assert key_alignment["prediction_keys"] == 1160
    assert key_alignment["report_keys"] == 1160
    assert key_alignment["no_missing_gold"] is True
    assert key_alignment["no_missing_prompts"] is True
    assert key_alignment["no_orphan_prompts"] is True
    assert key_alignment["no_orphan_predictions"] is True
    assert key_alignment["no_duplicates"] is True


def test_strict_and_valid_decision_denominators_diverge(audit: dict[str, object]) -> None:
    valid_layer = audit["layers"]["valid_output"]
    strict_layer = audit["layers"]["strict_end_to_end"]

    assert valid_layer["decision_accuracy"]["denominator"] == 501
    assert valid_layer["decision_accuracy"]["numerator"] == 335
    assert valid_layer["decision_accuracy"]["value"] == pytest.approx(335 / 501)

    assert strict_layer["decision_accuracy"]["denominator"] == 693
    assert strict_layer["decision_accuracy"]["numerator"] == 335
    assert strict_layer["decision_accuracy"]["value"] == pytest.approx(335 / 693)
    assert strict_layer["decision_accuracy"]["value"] < valid_layer["decision_accuracy"]["value"]


def test_boolean_confusion_audit_is_not_a_namespace_bug(audit: dict[str, object]) -> None:
    boolean_audit = audit["boolean_confusion_audit"]

    assert boolean_audit["count"] == 291
    assert boolean_audit["gold_distribution"] == {"true": 138, "false": 153}
    assert boolean_audit["predicted_distribution"] == {"true": 0, "false": 1, "missing": 290}
    assert boolean_audit["raw_answer_distribution"] == {"missing": 290, "json_false": 1}
    assert boolean_audit["confusion_matrix"]["false"]["false"] == 1
    assert boolean_audit["confusion_matrix"]["true"]["true"] == 0
    assert boolean_audit["accuracy_by_class"]["true"] == 0.0
    assert boolean_audit["accuracy_by_class"]["false"] == pytest.approx(1 / 153)
    assert len(boolean_audit["representative_errors"]) == 20
    assert all(not row["exact_comparison"] for row in boolean_audit["representative_errors"])


def test_format_failure_audit_counts(audit: dict[str, object]) -> None:
    format_failure_audit = audit["format_failure_audit"]
    category_counts = format_failure_audit["category_counts"]

    assert format_failure_audit["count"] == 239
    assert sum(category_counts.values()) == 239
    assert category_counts["wrong_json_type_decision"] == 182
    assert category_counts["noncanonical_free_text_boolean"] == 26
    assert category_counts["noncanonical_free_text_integer"] == 13
    assert category_counts["noncanonical_free_text_datetime"] == 4
    assert category_counts["noncanonical_free_text_code_set"] == 4
    assert category_counts["noncanonical_free_text_threshold"] == 2
    assert category_counts["noncanonical_free_text_date_range"] == 2
    assert category_counts["other_categorical"] == 3
    assert category_counts["other_code_set"] == 3


def test_counterfactual_strict_and_valid_pair_accounting(audit: dict[str, object]) -> None:
    counterfactual = audit["counterfactual"]

    assert counterfactual["ab_flip"]["strict"]["numerator"] == 17
    assert counterfactual["ab_flip"]["strict"]["denominator"] == 99
    assert counterfactual["ab_flip"]["valid_pair"]["denominator"] == 18

    assert counterfactual["ab_invariant"]["strict"]["numerator"] == 73
    assert counterfactual["ab_invariant"]["strict"]["denominator"] == 181
    assert counterfactual["ab_invariant"]["valid_pair"]["denominator"] == 75

    assert counterfactual["ac_nuisance_flip"]["strict"]["numerator"] == 30
    assert counterfactual["ac_nuisance_flip"]["strict"]["denominator"] == 55
    assert counterfactual["ac_nuisance_flip"]["valid_pair"]["denominator"] == 30

    assert counterfactual["ac_causal_invariant"]["strict"]["numerator"] == 61
    assert counterfactual["ac_causal_invariant"]["strict"]["denominator"] == 221
    assert counterfactual["ac_causal_invariant"]["valid_pair"]["denominator"] == 63

    assert counterfactual["strict"]["missed_update_numerator"] == 107
    assert counterfactual["strict"]["missed_update_denominator"] == 154
    assert counterfactual["valid_pair"]["missed_update_numerator"] == 1
    assert counterfactual["valid_pair"]["missed_update_denominator"] == 48
    assert counterfactual["strict"]["over_update_numerator"] == 268
    assert counterfactual["strict"]["over_update_denominator"] == 402
    assert counterfactual["valid_pair"]["over_update_numerator"] == 4
    assert counterfactual["valid_pair"]["over_update_denominator"] == 138
