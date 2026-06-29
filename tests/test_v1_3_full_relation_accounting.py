from __future__ import annotations

from pathlib import Path

import pytest

from rudocground.metrics import evaluate_report


FULL_GOLD = Path("data/v1_3_full_gold.jsonl")
FULL_PREDICTIONS = Path("results/qwen3.5-4b_v1.3.1_compact_full_predictions.jsonl")


def test_full_v1_3_counterfactual_uses_namespaced_relation_accounting():
    report = evaluate_report(str(FULL_GOLD), str(FULL_PREDICTIONS))
    counterfactual = report.counterfactual

    assert counterfactual["ab_flip_denominator"] == 99
    assert counterfactual["ab_invariance_denominator"] == 181
    assert counterfactual["ac_nuisance_detection_denominator"] == 55
    assert counterfactual["ac_causal_invariance_denominator"] == 221
    assert counterfactual["ab_flip_denominator"] + counterfactual["ab_invariance_denominator"] == 280
    assert counterfactual["ac_nuisance_detection_denominator"] + counterfactual["ac_causal_invariance_denominator"] == 276
    assert len(counterfactual["rows"]) == 556
    assert {"ab_flip", "ab_invariant", "ac_nuisance_flip", "ac_causal_invariant"} <= set(counterfactual["namespaces"])
    assert counterfactual["flip_score"] == pytest.approx(counterfactual["ab_flip_score"])
    assert counterfactual["invariance_score"] == pytest.approx(counterfactual["ab_invariance_score"])
    assert counterfactual["legacy"]["flip_count"] == 55
    assert counterfactual["legacy"]["invariance_count"] == 105
