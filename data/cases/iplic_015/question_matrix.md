| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the territory license scope case? | categorical | license_agreement | license_agreement | license_agreement | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | LIC-1501 | LIC-1501 | LIC-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-09-01T12:00:00 | 2026-09-01T12:00:00 | 2026-09-01T12:18:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Does the license cover the second region? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the territory scope outcome? | categorical | single_region | two_regions | single_region | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | How many regions are covered in the core record? | integer | 1 | 2 | 1 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What renewal date is recorded in the core record? | date | 2026-09-01 | 2026-09-30 | 2026-09-01 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the license scope? | code_set | ['territory_scope', 'renewal_gate'] | ['territory_scope', 'renewal_gate'] | ['territory_scope', 'renewal_gate'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | LIC-1501 | LIC-1501 | LIC-1501 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | license_agreement | license_agreement | license_agreement | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | single_region | two_regions | single_region | flip | invariant | decision_memo#final_status | substantive flip |
