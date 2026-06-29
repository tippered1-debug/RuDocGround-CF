| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the currency clause trigger case? | categorical | fx_clause | fx_clause | fx_clause | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | FX-1201 | FX-1201 | FX-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-07-01T10:00:00 | 2026-07-01T10:00:00 | 2026-07-01T10:11:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Does the FX threshold condition hold? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the final payment basis? | categorical | not_indexed | indexed | not_indexed | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | What payable amount is recorded in the core record? | money | 10000 | 12000 | 10000 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What deadline date is recorded in the core record? | date | 2026-07-01 | 2026-07-15 | 2026-07-01 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the currency clause? | code_set | ['threshold_check', 'fx_indexation'] | ['threshold_check', 'fx_indexation'] | ['threshold_check', 'fx_indexation'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | FX-1201 | FX-1201 | FX-1201 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | fx_clause | fx_clause | fx_clause | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | not_indexed | indexed | not_indexed | flip | invariant | decision_memo#final_status | substantive flip |
