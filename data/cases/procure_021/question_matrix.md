| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the single-source justification case? | categorical | sole_source_policy | sole_source_policy | sole_source_policy | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | PROC-2101 | PROC-2101 | PROC-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-11-01T14:00:00 | 2026-11-01T14:00:00 | 2026-11-01T14:10:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Is the sole-source justification complete? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the procurement-support outcome? | categorical | incomplete | complete | incomplete | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | How many mandatory comparators are documented in the core record? | integer | 2 | 1 | 2 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What checklist date is recorded in the core record? | date | 2026-11-01 | 2026-11-03 | 2026-11-01 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the sole-source file? | code_set | ['sole_source', 'comparator_check'] | ['sole_source', 'comparator_check'] | ['sole_source', 'comparator_check'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | PROC-2101 | PROC-2101 | PROC-2101 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | False | False | False | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | True | True | True | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | sole_source_policy | sole_source_policy | sole_source_policy | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | blocked | approved | blocked | flip | invariant | decision_memo#final_status | substantive flip |
