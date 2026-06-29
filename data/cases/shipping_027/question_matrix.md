| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the freight liability transfer case? | categorical | freight_contract | freight_contract | freight_contract | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | FRT-2701 | FRT-2701 | FRT-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-08-10T17:00:00 | 2026-08-10T17:00:00 | 2026-08-10T17:12:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Does liability transfer at loading? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the freight-liability outcome? | categorical | shipper_liable | carrier_liable | shipper_liable | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | At which stage is the risk transfer recorded in the core record? | categorical | loading | unloading | loading | flip | invariant | core_record#amount | substantive flip |
| Q7 | What damage-report date is recorded in the core record? | date | 2026-08-10 | 2026-08-11 | 2026-08-10 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the freight file? | code_set | ['risk_transfer', 'bill_of_lading'] | ['risk_transfer', 'bill_of_lading'] | ['risk_transfer', 'bill_of_lading'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | FRT-2701 | FRT-2701 | FRT-2701 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | freight_contract | freight_contract | freight_contract | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | shipper_liable | carrier_liable | shipper_liable | flip | invariant | decision_memo#final_status | substantive flip |
