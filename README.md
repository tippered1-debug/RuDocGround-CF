# RuDocGround-CF

`data/gold.jsonl` is the canonical validated gold dataset for the current Git tag. A small format example lives in `examples/sample_gold.jsonl`.

Both batched modes use one engine:

- `rudocground/runners/batched.py` handles retry, resume, JSONL output, artifacts, manifests, ordering, and evaluation.
- `rudocground/runners/protocols/full.py` defines the full protocol.
- `rudocground/runners/protocols/compact.py` defines the compact `a/d/e/m` protocol.

The old runner modules remain as thin compatibility wrappers.

The compact protocol returns only a boolean missing-information flag. It reports `missing_information_detection_accuracy`; exact-set missing-information accuracy is unavailable. Gold missing-information lists are never copied into predictions.

```bash
uv sync
uv run --with pytest python -m pytest -q
uv run python -m rudocground evaluate --gold data/gold.jsonl --predictions results/model.jsonl
uv run python -m rudocground prepare-prompts --case data/cases/trip_001 --gold data/gold.jsonl --output prompts/
uv run python scripts/build_v1_3_statistics.py --output-dir results
```
