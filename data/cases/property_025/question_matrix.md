| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the lease renewal option window case? | categorical | lease_notice_rule | lease_notice_rule | lease_notice_rule | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | LEASE-2501 | LEASE-2501 | LEASE-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-12-15T10:00:00 | 2026-12-15T10:00:00 | 2026-12-15T10:07:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Was the renewal option exercised on time? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the lease-renewal outcome? | categorical | lapsed | renewed | lapsed | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | How many business days are recorded for the notice window? | integer | 30 | 29 | 30 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What notice deadline date is recorded in the core record? | date | 2026-12-31 | 2027-01-01 | 2026-12-31 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the lease notice? | code_set | ['option_window', 'delivery_proof'] | ['option_window', 'delivery_proof'] | ['option_window', 'delivery_proof'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | LEASE-2501 | LEASE-2501 | LEASE-2501 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | lease_notice_rule | lease_notice_rule | lease_notice_rule | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | lapsed | renewed | lapsed | flip | invariant | decision_memo#final_status | substantive flip |
