# RuDocGround-CF

RuDocGround-CF is a Python 3.12 toolkit and Russian-language benchmark for document-grounded extraction, decision making, evidence selection, missing-information handling, and counterfactual evaluation.

## Repository layout

- `data/gold.jsonl` is the canonical validated gold dataset for the current Git tag.
- `data/cases/<case_id>/` contains the A/B/C counterfactual packages, manifests, and generated contexts.
- `data/source_documents/<case_id>/` contains the source documents used to build the case packages.
- `examples/sample_gold.jsonl` is a small gold-record format example.
- `prompts/` contains prepared prompt JSONL bundles.
- `rudocground/runners/` contains shared execution engines and protocol adapters.
- `results/` contains frozen model outputs, reports, and publication artifacts.
- `docs/` contains the article and supporting documentation.

The dataset version is defined by the Git tag and release metadata. A second versioned gold filename is intentionally not maintained.

## Evaluate saved predictions

Use the evaluator on already saved model outputs:

```bash
python -m rudocground evaluate \
  --gold data/gold.jsonl \
  --predictions results/model.jsonl
```

The report includes answer accuracy, decision accuracy, evidence precision/recall/F1, missing-information metrics, unsupported evidence rate, Flip Score, and Invariance Score. `decision_accuracy` is computed only for rows where `decision_required=true`; factual extraction rows are excluded from that denominator and report `decision_correct=null`.

## Batched inference architecture

Both batched protocols now use one execution engine:

- `rudocground/runners/batched.py` handles grouping, retries, resume, JSONL append, batch artifacts, manifests, raw responses, ordering, deduplication, and evaluation.
- `rudocground/runners/protocols/full.py` defines the full structured-response protocol.
- `rudocground/runners/protocols/compact.py` defines the compact `a/d/e/m` protocol.
- `rudocground/variant_batched_runner.py` and `rudocground/variant_batched_compact_runner.py` remain as thin compatibility wrappers for existing CLI imports.

The compact protocol returns only a boolean missing-information flag `m`. It therefore reports `missing_information_detection_accuracy`. Exact-set `missing_information_accuracy` is unavailable for this protocol, and the runner never copies the gold missing-information list into model predictions.

## RuDocGround-CF v1.3.1 release

Two inference protocols are preserved in the benchmark history:

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
- valid-pair flip and invariance metrics for counterfactual accounting

Protocol effect is substantial:

- batched compact answer accuracy: `0.7586`
- independent strict answer accuracy: `0.2845`
- boolean canonical success: `1/291`
- predictions hash: `08567e35fa0bcc595bd70076494c10e7341ada75d4e76bbbaee256f3ce3f5759`

The historical compact report predates the corrected missing-information contract. New compact runs must report detection accuracy rather than exact-set missing-information accuracy.

### Release contents

The canonical release is packaged so a clean clone can reproduce the benchmark, prompts, evaluation, and statistics.

- frozen benchmark data and manifests under `data/`
- prepared prompt bundles under `prompts/`
- independent and batched prediction/report artifacts under `results/`
- publication figures and bootstrap statistics under `results/statistics/`
- the final article PDF under `docs/`
- release metadata, citation, and license files at the repository root

Reproduction commands from a clean clone:

```bash
uv sync
uv run --with pytest python -m pytest -q
uv run python -m rudocground audit-cases \
  --case data/cases/trip_001
uv run python -m rudocground prepare-prompts \
  --case data/cases/trip_001 \
  --gold data/gold.jsonl \
  --output prompts/
uv run python -m rudocground evaluate-run \
  --gold data/gold.jsonl \
  --predictions results/qwen3.5-4b_v1.3.1_independent_full_predictions.jsonl \
  --report results/qwen3.5-4b_v1.3.1_independent_full_report_corrected.json
uv run python -m rudocground strict-audit \
  --gold data/gold.jsonl \
  --predictions results/qwen3.5-4b_v1.3.1_independent_full_predictions.jsonl \
  --prompts prompts/v1_3_full_prompts.jsonl \
  --output-dir results/statistics \
  --prefix qwen3.5-4b_v1.3.1_independent_full
uv run python scripts/build_v1_3_statistics.py --output-dir results
```

`strict-audit` is the publication-facing reproduction path. On the frozen 1160-task release it returns:

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

Check package structure and source-document fidelity:

```bash
python -m rudocground audit-cases \
  --case data/cases/trip_001

python -m rudocground audit-source-fidelity \
  --case data/cases/trip_001 \
  --sources data/source_documents/trip_001

python -m rudocground audit-cases \
  --case data/cases/authority_003
```

`audit-cases` checks manifests, filenames, counts, hashes, and counterfactual package structure. `audit-source-fidelity` additionally verifies source-document identity and that evidence locators resolve in the extracted text.

## Generate prompts

Build prompt JSONL files from a case package and the canonical gold data:

```bash
python -m rudocground prepare-prompts \
  --case data/cases/trip_001 \
  --gold data/gold.jsonl \
  --output prompts/
```

This writes:

- `prompts/trip_001_A.jsonl`
- `prompts/trip_001_B.jsonl`
- `prompts/trip_001_all.jsonl`

The prompt text includes the full extracted context for each variant in manifest order.

## Run a model

The universal runner supports configured model providers and writes normalized prediction rows plus raw metadata:

```bash
python -m rudocground run-model \
  --prompts prompts/trip_001_all.jsonl \
  --provider openai \
  --model MODEL_NAME \
  --output results/MODEL_NAME.jsonl
```

Dry runs validate the prompt bundle without calling a provider:

```bash
python -m rudocground run-model \
  --prompts prompts/trip_001_all.jsonl \
  --provider openai \
  --model MODEL_NAME \
  --output results/MODEL_NAME.jsonl \
  --dry-run
```

Use `--policy answer_only`, `--policy structured`, or `--policy evidence_required` for the three experimental prompt modes.

## Evaluate a saved run

After a run is saved, produce a detailed JSON report and CSV:

```bash
python -m rudocground evaluate-run \
  --gold data/gold.jsonl \
  --predictions results/MODEL_NAME.jsonl \
  --report results/MODEL_NAME_report.json
```

## Evaluator self-checks

Three controlled prediction fixtures are included:

- `results/perfect.jsonl` mirrors the gold answers and should yield 1.0 on the main metrics.
- `results/broken.jsonl` includes controlled mistakes so Flip Score, Invariance Score, and evidence metrics move below 1.0.
- `results/partial.jsonl` omits some answers and includes malformed or duplicate rows to exercise validation.

```bash
python -m rudocground evaluate \
  --gold data/gold.jsonl \
  --predictions results/perfect.jsonl

python -m rudocground evaluate \
  --gold data/gold.jsonl \
  --predictions results/broken.jsonl

python -m rudocground evaluate \
  --gold data/gold.jsonl \
  --predictions results/partial.jsonl
```

## Tests

```bash
uv run --with pytest python -m pytest -q
```
