from __future__ import annotations

from pathlib import Path

import pytest

from rudocground.statistics import (
    build_statistics_artifacts,
    load_batched_dataset,
    load_independent_dataset,
    paired_protocol_effect,
    sample_case_clusters,
)


GOLD = Path("data/v1_3_full_gold.jsonl")
INDEPENDENT_PREDICTIONS = Path("results/qwen3.5-4b_v1.3.1_independent_full_predictions.jsonl")
INDEPENDENT_COUNTERFACTUAL = Path("results/qwen3.5-4b_v1.3.1_independent_full_counterfactual_corrected.json")
INDEPENDENT_BUNDLE = Path("results/qwen3.5-4b_v1.3.1_release_bundle.json")
BATCHED_REPORT = Path("results/qwen3.5-4b_v1.3.1_compact_full_report.json")
BATCHED_COUNTERFACTUAL = Path("results/qwen3.5-4b_v1.3.1_compact_full_counterfactual.json")
BATCHED_MANIFEST = Path("results/qwen3.5-4b_v1.3.1_compact_full_manifest.json")


@pytest.fixture(scope="module")
def datasets() -> tuple[object, object]:
    return (
        load_independent_dataset(
            gold_path=GOLD,
            predictions_path=INDEPENDENT_PREDICTIONS,
            counterfactual_path=INDEPENDENT_COUNTERFACTUAL,
            release_bundle_path=INDEPENDENT_BUNDLE,
        ),
        load_batched_dataset(
            report_path=BATCHED_REPORT,
            counterfactual_path=BATCHED_COUNTERFACTUAL,
            compact_report_path=BATCHED_REPORT,
        ),
    )


def test_case_cluster_sampler_is_case_id_based() -> None:
    case_ids = [f"case_{i}" for i in range(30)]
    samples = sample_case_clusters(case_ids, replicates=3, seed=42)
    assert len(samples) == 3
    assert all(len(sample) == 30 for sample in samples)
    assert all(item in case_ids for sample in samples for item in sample)


def test_seed_is_reproducible() -> None:
    case_ids = [f"case_{i}" for i in range(30)]
    first = sample_case_clusters(case_ids, replicates=5, seed=42)
    second = sample_case_clusters(case_ids, replicates=5, seed=42)
    third = sample_case_clusters(case_ids, replicates=5, seed=7)
    assert first == second
    assert first != third


def test_point_estimates_match_release_bundle(datasets: tuple[object, object]) -> None:
    independent, batched = datasets
    assert independent.point_estimates["answer_accuracy"] == pytest.approx(0.28448275862068967)
    assert independent.point_estimates["decision_accuracy"] == pytest.approx(0.4834054834054834)
    assert independent.point_estimates["missing_information_accuracy"] == pytest.approx(0.7836206896551724)
    assert independent.point_estimates["evidence_f1"] == pytest.approx(0.42535851122058016)
    assert batched.point_estimates["answer_accuracy"] == pytest.approx(0.7586206896551724)
    assert batched.point_estimates["decision_accuracy"] == pytest.approx(0.7806637806637806)


def test_paired_protocol_effect_uses_same_case_sample(datasets: tuple[object, object]) -> None:
    independent, batched = datasets
    samples = sample_case_clusters(independent.case_ids, replicates=2, seed=42)
    deltas = paired_protocol_effect(batched, independent, samples)
    assert [row["sampled_cases"] for row in deltas] == ["|".join(sample) for sample in samples]
    assert deltas[0]["replicate"] == 0
    assert deltas[1]["replicate"] == 1


def test_bootstrap_artifact_builder_runs_on_case_clusters(tmp_path: Path) -> None:
    summary = build_statistics_artifacts(
        gold_path=GOLD,
        independent_predictions_path=INDEPENDENT_PREDICTIONS,
        independent_counterfactual_path=INDEPENDENT_COUNTERFACTUAL,
        independent_release_bundle_path=INDEPENDENT_BUNDLE,
        batched_report_path=BATCHED_REPORT,
        batched_counterfactual_path=BATCHED_COUNTERFACTUAL,
        batched_manifest_path=BATCHED_MANIFEST,
        output_dir=tmp_path,
        seed=42,
        replicates=25,
    )
    assert Path(summary["case_bootstrap_summary"]).exists()
    assert Path(summary["protocol_effect_summary"]).exists()
    assert Path(summary["case_bootstrap_distributions"]).exists()
    assert Path(summary["protocol_effect_distributions"]).exists()
    assert Path(summary["case_level_comparison"]).exists()
    assert summary["seed"] == 42
    assert summary["replicates"] == 25

