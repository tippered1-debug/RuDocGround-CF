| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the security deposit offset case? | categorical | lease_guarantee_clause | lease_guarantee_clause | lease_guarantee_clause | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | LEASE-2601 | LEASE-2601 | LEASE-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-10-15T09:00:00 | 2026-10-15T09:00:00 | 2026-10-15T09:13:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Is the deposit offset allowed? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the deposit-offset outcome? | categorical | not_allowed | allowed | not_allowed | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | What deposit offset amount is recorded in the core record? | money | 20000 | 0 | 20000 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What repair-act date is recorded in the core record? | date | 2026-10-15 | 2026-10-16 | 2026-10-15 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the deposit offset? | code_set | ['offset_gate', 'repair_act'] | ['offset_gate', 'repair_act'] | ['offset_gate', 'repair_act'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | LEASE-2601 | LEASE-2601 | LEASE-2601 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | lease_guarantee_clause | lease_guarantee_clause | lease_guarantee_clause | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | not_allowed | allowed | not_allowed | flip | invariant | decision_memo#final_status | substantive flip |
