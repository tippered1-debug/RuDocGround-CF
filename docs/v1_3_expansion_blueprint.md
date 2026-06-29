# RuDocGround-CF v1.3 Expansion Blueprint

## Scope

This blueprint proposes an expansion from 10 to 30 independent cases for RuDocGround-CF.
It does not create final case packages, gold files, or the 640 new task rows.
It only defines the candidate registry, the pilot subset, coverage matrices, and the independence audit.

## What already exists in v1.2

The current benchmark is dominated by a small cluster of business-process patterns:

- travel and expense reconciliation
- authority / power-of-attorney scope
- acceptance and service completion
- procurement approval
- renewal notice timing
- SLA / service reporting
- access approval chains
- amendment / pricing changes
- asset scope and billing eligibility

This gives good baseline coverage for:

- document chaining
- date-sensitive decisions
- scope-based interpretation
- some payment eligibility decisions

It is still thin or absent in:

- supply chain and logistics exceptions
- IP / licensing scope
- privacy and information security
- HR access revocation / role change
- procurement compliance exceptions
- property / lease / guarantee logic
- mixed-document contradictions that force conflict resolution outside authority cases

## v1.3 expansion design principles

1. Each case must be a distinct business situation with its own document set.
2. The A/B perturbation must be local, explicit, and singular.
3. Cases should not differ only by company names, numbers, or dates.
4. Each case should exercise a different causal mechanism.
5. Each case must support extraction, decision, evidence, and missing-information tasks.
6. Gold must remain recoverable only from documents, not from schema naming.
7. Canonical answer contracts must stay structured and non-freeform.

## Proposed 20 candidate cases

The registry below intentionally spans the requested domains:

- finance and calculations
- supply and logistics
- licenses and intellectual property
- personal data and information security
- HR, access, and authority
- procurement and compliance
- IT / SLA
- lease, property, and guarantees

### Candidate list

| case_id | short name | domain | perturbation | primary skill | answer types |
|---|---|---|---|---|---|
| finset_011 | Partial prepayment threshold | finance and calculations | a single line-item surcharge is moved between taxable and non-taxable scope | numeric reconciliation | amount, yes_no, enum |
| finset_012 | Currency clause trigger | finance and calculations | FX indexation clause activates only under a documented threshold | threshold interpretation | amount, date, enum |
| logistics_013 | Split shipment acceptance | supply and logistics | delivery is split across two warehouses vs one consolidated receipt | chain-of-custody reasoning | date, enum, yes_no |
| logistics_014 | Temperature excursion hold | supply and logistics | one monitoring log shows a cold-chain excursion above limit | evidence conflict resolution | yes_no, enum, boolean |
| iplic_015 | Territory license scope | licenses and IP | distribution territory is narrowed to one region | scope limitation reasoning | yes_no, enum, date |
| iplic_016 | Source-code escrow release | licenses and IP | escrow release condition is met by a single failed support response | conditional contract logic | yes_no, enum, text_enum |
| privacy_017 | Personal-data transfer basis | privacy and infosec | legal basis changes from consent to contract necessity | compliance reasoning | yes_no, enum, multi_select |
| privacy_018 | Security incident notification clock | privacy and infosec | incident discovery time shifts across the 72-hour clock | time window reasoning | date, yes_no, enum |
| hr_019 | Role change and access revocation | HR, access, authority | employment end date moves before access approval date | authorization timing | yes_no, date, enum |
| hr_020 | Delegated authority gap | HR, access, authority | signer delegation excludes a specific contract class | authority scope reasoning | yes_no, enum |
| procure_021 | Single-source justification | procurement and compliance | justification memo lacks one mandatory comparator | missing-information reasoning | yes_no, enum, missing |
| procure_022 | Conflicted vendor certifications | procurement and compliance | anti-bribery certificate contradicts registry entry | contradiction resolution | yes_no, enum, evidence_link |
| it_023 | SLA penalty waiver | IT / SLA | service credits waived only if outage report filed on time | timing + clause precedence | amount, yes_no, enum |
| it_024 | Escalation path breach | IT / SLA | incident is escalated to wrong tier before SLA clock stops | process compliance | yes_no, enum, date |
| property_025 | Lease renewal option window | lease, property, guarantees | notice window is one business day earlier in B | timing / option exercise | yes_no, date, enum |
| property_026 | Security deposit offset | lease, property, guarantees | offset right exists only if repair act is signed | conditional offset | amount, yes_no, enum |
| shipping_027 | Freight liability transfer | supply and logistics | risk transfer moves from loading to unloading | liability allocation | yes_no, enum, date |
| finance_028 | Advance report substantiation | finance and calculations | one receipt becomes non-reimbursable due to missing approver | evidence sufficiency | amount, yes_no, enum |
| infosec_029 | Privileged account emergency use | privacy and infosec | emergency access expires sooner in B | access + time condition | yes_no, enum, date |
| hr_030 | Exit checklist completion | HR, access, authority | one return-of-assets item is absent | completion / missing-info | yes_no, enum, missing |

### Causal mechanism taxonomy

The 20 candidates are intentionally distributed across distinct reasoning mechanisms:

- threshold crossing
- temporal trigger
- scope inclusion
- authority coverage
- document conflict
- document hierarchy
- chain completion
- missing evidence
- multi-document reconciliation
- proportional entitlement
- exception or waiver
- identity or asset linkage

The registry stores one primary mechanism per case together with the nearest existing v1.2 case and an independence score.

## Reworked close cases

These six candidates were revised because they sat too near old v1.2 patterns:

### `logistics_013`

- old concept: split shipment acceptance
- new concept: split custody chain reconciliation for a shipment that traverses two parallel custody chains
- new reasoning mechanism: chain completion
- why it is different: the question is no longer whether a delivery was accepted, but which custody chain controls final acceptance

### `hr_020`

- old concept: delegated authority gap
- new concept: delegated signing scope gap
- new reasoning mechanism: authority coverage
- why it is different: the case now hinges on whether the delegated signature class itself is covered, not simply whether authority exists

### `procure_021`

- old concept: single-source justification
- new concept: incomplete sole-source justification with a missing comparator
- new reasoning mechanism: missing evidence
- why it is different: the blocking condition is an absent mandatory comparator, not a normal approval-chain question

### `it_023`

- old concept: SLA penalty waiver
- new concept: waiver against service credit when outage reporting is late
- new reasoning mechanism: exception or waiver
- why it is different: the key question is waiver eligibility under the clause, not generic SLA timing

### `it_024`

- old concept: escalation path breach
- new concept: escalation routing correctness under an SLA schedule
- new reasoning mechanism: document hierarchy
- why it is different: the core question is whether the escalation path matches the required matrix, not whether response time is met

### `property_025`

- old concept: lease renewal option window
- new concept: lease option exercise window with delivery proof and business-day counting
- new reasoning mechanism: temporal trigger
- why it is different: the timing controls option exercise under lease logic, not automatic notice renewal

## Proposed pilot set

The five pilots are selected to maximize diversity and avoid close reuse of existing mechanisms:

1. `logistics_014`
2. `iplic_016`
3. `privacy_017`
4. `hr_019`
5. `procure_022`

### Pilot 1: `logistics_014`

- documents and roles:
  - `temperature_sla`: controlling threshold document
  - `monitoring_log`: factual measurement source
  - `complaint`: counterparty challenge
  - `hold_notice`: operational decision record
  - `delivery_note`: shipping baseline
  - `call_center_note`: non-controlling support narrative
- structure of variant A:
  - baseline cold-chain delivery with one coherent monitoring series and consistent acceptance posture
- exact change in variant B:
  - one monitoring reading crosses the allowable temperature limit
- pilot questions:
  - Was the shipment acceptable?
  - Does the hold notice stand?
  - Is rejection justified?
  - What product type is listed?
  - Which route was used?
  - What is the consignee name?
  - Is the complaint timely?
  - Does the threshold apply to all legs?
  - Was the monitoring log complete?
  - Is the hold notice supported?
  - Was the shipment rejected for cause?
  - Is the temperature reading the controlling fact?
- flip questions:
  - Was the shipment acceptable?
  - Does the hold notice stand?
  - Is rejection justified?
  - Is the complaint timely?
  - Does the threshold apply to all legs?
  - Was the hold notice supported?
  - Was the shipment rejected for cause?
  - Is the temperature reading the controlling fact?
- invariant questions:
  - What product type is listed?
  - Which route was used?
  - What is the consignee name?
  - Was the monitoring log complete?
- canonical answer types:
  - yes_no
  - enum
  - boolean
- evidence source:
  - monitoring_log for the changed fact
  - hold_notice and temperature_sla for decision justification
  - delivery_note and complaint for invariant metadata
- possible ambiguities:
  - whether the legal threshold is a single-leg or all-legs condition
  - whether the complaint is merely supportive or independently dispositive

### Pilot 2: `iplic_016`

- documents and roles:
  - `escrow_agreement`: controlling release clause
  - `support_log`: trigger evidence
  - `release_request`: requested action
  - `counsel_memo`: interpretive hierarchy
  - `license_notice`: surrounding context
- structure of variant A:
  - baseline support interaction that does not yet meet the release trigger
- exact change in variant B:
  - support failure or response timeout satisfies the escrow trigger
- pilot questions:
  - Is the escrow releasable?
  - What trigger was met?
  - Is notice valid?
  - Has the response deadline expired?
  - Does the counsel memo support release?
  - Is the request premature?
  - Is the support log complete?
  - Does the escrow agreement control over the notice?
  - Is the release request sufficient?
  - Which party may receive source code?
  - Is the trigger technical or legal?
  - Is the trigger documented?
- flip questions:
  - Is the escrow releasable?
  - What trigger was met?
  - Is the request premature?
  - Does the escrow agreement control over the notice?
  - Which party may receive source code?
  - Is the trigger technical or legal?
  - Is the trigger documented?
- invariant questions:
  - Is notice valid?
  - Has the response deadline expired?
  - Does the counsel memo support release?
  - Is the support log complete?
  - Is the release request sufficient?
- canonical answer types:
  - yes_no
  - enum
  - text_enum
- evidence source:
  - escrow_agreement and support_log for trigger logic
  - counsel_memo for hierarchy
  - license_notice for unchanged context
- possible ambiguities:
  - whether the release condition is conjunctive or disjunctive
  - whether the support failure is measured by response time or outright failure

### Pilot 3: `privacy_017`

- documents and roles:
  - `dpa`: processor obligations
  - `privacy_notice`: baseline disclosure
  - `transfer_assessment`: data-transfer gate
  - `onsite_request`: operational context
  - `legal_memo`: internal interpretation
- structure of variant A:
  - transfer is assessed under the consent-based route and remains unresolved or disallowed
- exact change in variant B:
  - legal basis changes from consent to contract necessity
- pilot questions:
  - Is the transfer permitted?
  - Which legal basis applies?
  - Is a separate consent required?
  - Is the transfer cross-border?
  - Does the DPA authorize the transfer?
  - Is the privacy notice sufficient?
  - Does the legal memo override the notice?
  - Is the onsite request relevant?
  - Is the transfer assessment complete?
  - Is consent still needed?
  - Is the basis contractual?
  - Does the change affect all recipients?
- flip questions:
  - Is the transfer permitted?
  - Which legal basis applies?
  - Is a separate consent required?
  - Does the legal memo override the notice?
  - Is consent still needed?
  - Is the basis contractual?
  - Does the change affect all recipients?
- invariant questions:
  - Is the transfer cross-border?
  - Does the DPA authorize the transfer?
  - Is the privacy notice sufficient?
  - Is the onsite request relevant?
  - Is the transfer assessment complete?
- canonical answer types:
  - yes_no
  - enum
  - multi_select
- evidence source:
  - transfer_assessment for permissibility
  - dpa and legal_memo for basis selection
  - privacy_notice for unchanged disclosure facts
- possible ambiguities:
  - whether the internal memo is enough to establish the contractual basis
  - whether cross-border status alone is sufficient for the transfer decision

### Pilot 4: `hr_019`

- documents and roles:
  - `hr_memo`: employment status event
  - `access_request`: requested system permission
  - `termination_note`: offboarding timestamp
  - `iam_log`: technical evidence of access
  - `manager_approval`: supervisory acknowledgment
- structure of variant A:
  - access is requested while employment is still active
- exact change in variant B:
  - employment end date precedes access approval
- pilot questions:
  - Was access valid when granted?
  - Should rights be revoked?
  - What date controls authority?
  - Is the employee still active?
  - Does the IAM log show authorization?
  - Is manager approval sufficient?
  - Does the termination note predate approval?
  - Is the access request timely?
  - Is the system covered by the memo?
  - Is the offboarding complete?
  - Is the grant effective?
  - Is revocation required?
- flip questions:
  - Was access valid when granted?
  - Should rights be revoked?
  - What date controls authority?
  - Does the termination note predate approval?
  - Is the grant effective?
  - Is revocation required?
- invariant questions:
  - Is the employee still active?
  - Does the IAM log show authorization?
  - Is manager approval sufficient?
  - Is the access request timely?
  - Is the system covered by the memo?
  - Is the offboarding complete?
- canonical answer types:
  - yes_no
  - date
  - enum
- evidence source:
  - hr_memo and termination_note for status timing
  - access_request and manager_approval for authorization path
  - iam_log for implementation evidence
- possible ambiguities:
  - whether approval time or effective time controls authority
  - whether offboarding status alone revokes access

### Pilot 5: `procure_022`

- documents and roles:
  - `vendor_submission`: vendor statement
  - `certificate`: compliance attestation
  - `registry_extract`: external-register-like factual check
  - `due_diligence_note`: internal evaluation
  - `approval_sheet`: decision record
- structure of variant A:
  - certificate and registry are aligned, allowing ordinary compliance review
- exact change in variant B:
  - certificate and registry disagree on compliance status
- pilot questions:
  - Is the vendor eligible?
  - Which document prevails?
  - Is the certificate valid?
  - Does the registry conflict matter?
  - Is the approval sheet sufficient?
  - Is due diligence complete?
  - Does the mismatch require escalation?
  - Is the vendor submission credible?
  - Is the certificate current?
  - Is the conflict material?
  - Can the purchase proceed?
  - Is the registry extract controlling?
- flip questions:
  - Is the vendor eligible?
  - Which document prevails?
  - Is the certificate valid?
  - Does the registry conflict matter?
  - Does the mismatch require escalation?
  - Is the conflict material?
  - Can the purchase proceed?
  - Is the registry extract controlling?
- invariant questions:
  - Is the approval sheet sufficient?
  - Is due diligence complete?
  - Is the vendor submission credible?
  - Is the certificate current?
- canonical answer types:
  - yes_no
  - enum
  - evidence_link
- evidence source:
  - certificate and registry_extract for conflict
  - due_diligence_note for interpretive outcome
  - approval_sheet for final disposition
- possible ambiguities:
  - whether the registry is merely corroborative or controlling
  - whether conflict resolution requires a hierarchy rule already in the documents

### Optional D candidate

For `procure_022`, a future non-required variant `D` could combine:

- a certificate/registry mismatch
- plus a missing signature on the approval sheet

This is intentionally not generated now because it would test a two-factor perturbation and needs a separate preflight check.

This set covers at least four distinct business domains and includes:

- a missing-information case
- a document conflict case
- a temporal-condition case
- a permissions / access case
- a conditional-release case

## Scale target

Target benchmark size after full generation:

- existing cases: 10
- new cases: 20
- total cases: 30
- variants per case: 2
- total variants: 60
- questions per variant: 12 to 16
- existing task rows: 320
- new task rows: 560
- total task rows: 880
- A/B or A/B/C comparison pairs: 120
- expected-change pairs: 210
- expected-invariant pairs: 560
- other pairs not counted in contrastive metrics: 110

Sanity check:

- 210 expected-change pairs + 560 expected-invariant pairs = 770 contrastive pairs
- 770 contrastive pairs <= 880 total task rows
- comparison-pair counts stay below the total task-row count

Using 14 questions per variant as the planning midpoint:

- new task rows: 20 x 2 x 14 = 560
- benchmark total task rows: 320 + 560 = 880
- if every variant has A/B only, raw comparable pair slots = 60
- if all five pilots use A/B/C, pilot comparable pair slots = 15
- total comparison-pair planning budget = 120

### Document-grounded closure check

For each candidate, the registry now marks whether external law or professional knowledge is required.

Rules:

- if a case needs law, Incoterms, tax treatment, or notification windows, the manifest must include the controlling excerpt or internal policy
- if the answer can be derived fully from the documents, `gold_from_docs_only` stays `yes`
- if the package would still depend on unstated law, the case must be redesigned before generation

At the current blueprint stage:

- cases requiring explicit source inclusion: `privacy_017`, `privacy_018`, `hr_019`, `property_025`, `shipping_027`, `infosec_029`, `procure_021`
- cases that remain fully document-grounded after the manifest additions: the rest of the registry

Approximate model-run time for a full benchmark pass:

- 45 to 90 seconds per variant on a strong hosted model with retrieval and structured output
- 60 variants total
- end-to-end wall time: approximately 45 to 90 minutes

## Risks

1. Gold ambiguity can appear in cases with partial evidence and overlapping clauses.
2. Leakage risk is highest if answer contracts mirror document schemas too closely.
3. Some domains, especially privacy and procurement compliance, can collapse into yes/no-only patterns unless the document set is varied.
4. If all new cases use the same narrative structure, they will be too similar to the existing 10.
5. Cases with numeric answers need careful normalization so that canonical answers stay stable.

## Manual confirmation required before final generation

- final case names and case IDs
- whether the pilot set should remain as chosen here
- exact document manifests for each of the 20 cases
- the final question list per case
- the gold rationale text for each flip and invariant pair
- whether any case should be excluded for ambiguity after a preflight review

## Status

V1.3 EXPANSION BLUEPRINT READY
