# RuDocGround-CF v1.3.1 Dataset Card

## Summary

RuDocGround-CF v1.3.1 is a Russian-language document-grounded benchmark for structured extraction, decision making, evidence selection, and missing-information detection under counterfactual perturbations.

## Composition

- 30 independent business cases
- 80 variants across A/B/C protocols
- 1160 prompt/gold task rows
- 2 evaluation protocols:
  - `variant_batched_compact`
  - `independent_single_question`

## Domains

The benchmark spans:

- finance and calculations
- supply and logistics
- licensing and intellectual property
- privacy and information security
- HR, access, and authority
- procurement and compliance
- IT and SLA
- property, leasing, and guarantees

## Intended Use

Use the benchmark to measure:

- answer correctness
- decision correctness
- evidence grounding
- missing-information handling
- counterfactual flip sensitivity
- counterfactual invariance

## Scope and Evaluation Contract

- The benchmark is designed for Russian business-document workflows.
- The gold answers are canonical and should be evaluated only with the provided evaluator.
- The release includes both batched and independent protocols; they are not interchangeable.

## Reproducibility

The release includes:

- case manifests
- gold annotations
- prompt bundles
- model predictions
- corrected reports
- bootstrap statistics
- release and audit manifests

## Citation

Please cite the release and the accompanying article PDF included in `docs/`.
