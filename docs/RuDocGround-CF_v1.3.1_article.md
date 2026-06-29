# RuDocGround-CF v1.3.1 Release Article

## Abstract

RuDocGround-CF v1.3.1 is a frozen document-grounded benchmark for Russian business workflows. The release contains 30 cases, 80 variants, and 1160 canonical prompt/gold rows across two preserved evaluation protocols. The main release result is a strict end-to-end independent answer accuracy of 0.2845 with a strong protocol effect relative to the batched compact protocol.

## What is included

- benchmark case packages with canonical manifests
- gold annotations and prompt bundles
- batched and independent predictions
- corrected reports and counterfactual accounting
- case-cluster bootstrap statistics
- reproducibility manifests and hashes

## Main evaluation result

- independent strict answer accuracy: 0.2845
- decision accuracy: 0.4834
- missing-information accuracy: 0.7836
- evidence F1: 0.4254
- format failure rate: 239/1160

## Protocol effect

The batched compact protocol reaches answer accuracy 0.7586 on the same frozen benchmark. The gap is large enough to be visible at both the case level and in the bootstrap distribution of delta answer accuracy.

## Reproduction

The repository ships with scripts and manifests that support:

1. clean install
2. benchmark validation
3. prompt generation
4. evaluation of saved predictions
5. statistics reproduction
6. full pytest

## Citation

Use the accompanying `CITATION.cff` file for citation metadata.
