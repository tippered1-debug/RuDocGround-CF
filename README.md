# RuDocGround-CF

RuDocGround is a Python 3.12 toolkit for document-grounded evaluation and case preparation.

## Repository layout

- `data/gold.jsonl` stores the validated gold annotations.
- `data/cases/<case_id>/` stores the counterfactual packages, their manifest, and generated contexts.
- `data/source_documents/<case_id>/` stores the source documents used to build the case packages.
- `prompts/` stores generated prompt JSONL files.

## Evaluate saved predictions

Use the evaluator on already saved model outputs:

```bash
python -m rudocground evaluate --gold data/gold.jsonl --predictions results/model.jsonl
```

The report includes answer accuracy, decision accuracy, evidence precision/recall/F1, missing-information accuracy, unsupported evidence rate, Flip Score, and Invariance Score. `decision_accuracy` is computed only for rows where `decision_required=true`; factual extraction rows are excluded from that denominator and report `decision_correct=null`.

## RuDocGround-CF v1.3.1 Release

Two independent evaluation protocols are preserved in the benchmark history:

1. `variant_batched_compact`
2. `independent_single_question`

For the final Qwen3.5 4B release, the primary result is the strict end-to-end independent run:

- answer accuracy: `0.2845`
- decision accuracy: `0.4834`
- missing-information accuracy: `0.7836`
- evidence F1: `0.4254`
- format failure rate: `239/1160`

The following are conditional diagnostics, not the main production score:

- valid-output answer accuracy: `0.3583`
- valid-pair flip / invariance metrics for counterfactual accounting

Protocol effect is substantial:

- batched compact answer accuracy: `0.7586`
- independent strict answer accuracy: `0.2845`
- boolean canonical success: `1/291`
- predictions hash: `08567e35fa0bcc595bd70076494c10e7341ada75d4e76bbbaee256f3ce3f5759`

### Release contents

The canonical release is packaged so a clean clone can reproduce the benchmark, prompts, evaluation, and statistics.

- frozen benchmark data and manifests under `data/`
- prepared prompt bundles under `prompts/`
- independent and batched prediction/report artifacts under `results/`
- publication figures and bootstrap statistics under `results/statistics/`, including `results/statistics/counterfactual_strict_vs_valid_pair_scores.png`
- the final article PDF under `docs/`
- release metadata, citation, and license files at the repository root

Reproduction commands from a clean clone:

```bash
uv sync
uv run --with pytest python -m pytest -q
uv run python -m rudocground audit-cases --case data/cases/trip_001
uv run python -m rudocground prepare-prompts --case data/cases/trip_001 --gold data/v1_3_full_gold.jsonl --output prompts/
uv run python -m rudocground evaluate-run --gold data/v1_3_full_gold.jsonl --predictions results/qwen3.5-4b_v1.3.1_independent_full_predictions.jsonl --report results/qwen3.5-4b_v1.3.1_independent_full_report_corrected.json
uv run python -m rudocground strict-audit --gold data/v1_3_full_gold.jsonl --predictions results/qwen3.5-4b_v1.3.1_independent_full_predictions.jsonl --prompts prompts/v1_3_full_prompts.jsonl --output-dir results/statistics --prefix qwen3.5-4b_v1.3.1_independent_full
uv run python3 scripts/build_v1_3_statistics.py --output-dir results
```

The `strict-audit` command is the publication-facing reproduction path. On the frozen 1160-task release it returns the strict end-to-end metrics used in the paper:

- strict answer accuracy: `0.2844827586`
- strict decision accuracy: `0.4834054834`
- strict evidence F1: `0.4253585112`
- evaluable-output rate: `0.7939655172`
- terminal format failures: `239`

Release asset map:

- `release_manifest.json` enumerates the GitHub Release assets, their hashes, sizes, and the command that consumes each asset.
- The benchmark archive is produced from the frozen release tree.
- The statistics bundle contains bootstrap distributions and figure exports for publication.

## Case audits

Check the package structure and the source-document fidelity:

```bash
python -m rudocground audit-cases --case data/cases/trip_001
python -m rudocground audit-source-fidelity --case data/cases/trip_001 --sources data/source_documents/trip_001
python -m rudocground audit-cases --case data/cases/authority_003
```

`audit-cases` checks the package manifest, filenames, counts, hashes, and the A/B counterfactual split. `audit-source-fidelity` additionally verifies that the packages are copied from the source DOCX files, that the gold evidence points to existing documents, and that evidence locators resolve in the extracted text.

## Generate prompts

Build the prompt JSONL files from the case package and gold annotations:

```bash
python -m rudocground prepare-prompts --case data/cases/trip_001 --gold data/gold.jsonl --output prompts/
```

This writes:

- `prompts/trip_001_A.jsonl`
- `prompts/trip_001_B.jsonl`
- `prompts/trip_001_all.jsonl`

The prompt text includes the full extracted context for each variant in manifest order.

## Run a model

The universal runner supports OpenAI and test-time mock providers. It reads prepared prompt JSONL files and writes normalized prediction rows plus raw metadata:

```bash
python -m rudocground run-model --prompts prompts/trip_001_all.jsonl --provider openai --model MODEL_NAME --output results/MODEL_NAME.jsonl
```

Dry runs validate the prompt bundle without calling the API:

```bash
python -m rudocground run-model --prompts prompts/trip_001_all.jsonl --provider openai --model MODEL_NAME --output results/MODEL_NAME.jsonl --dry-run
```

Use `--policy answer_only`, `--policy structured`, or `--policy evidence_required` to run the three experimental prompt modes.
## Evaluate a saved run

After a run is saved, produce a detailed report and CSV:

```bash
python -m rudocground evaluate-run --gold data/gold.jsonl --predictions results/MODEL_NAME.jsonl --report results/MODEL_NAME_report.json
```

## Validator self-check

Three prediction sets are included for quick sanity checks:

- `results/perfect.jsonl` mirrors the gold answers and should yield 1.0 on the main metrics.
- `results/broken.jsonl` includes controlled mistakes so we can see Flip Score, Invariance Score, and evidence metrics move below 1.0.
- `results/partial.jsonl` omits some answers and mixes in malformed or duplicate rows so the loader and missing-answer checks are exercised.

Run the validator against all three sets and inspect the reports it emits:

```bash
python -m rudocground evaluate --gold data/gold.jsonl --predictions results/perfect.jsonl
python -m rudocground evaluate --gold data/gold.jsonl --predictions results/broken.jsonl
python -m rudocground evaluate --gold data/gold.jsonl --predictions results/partial.jsonl
```

## Run tests

```bash
pytest -q
```
