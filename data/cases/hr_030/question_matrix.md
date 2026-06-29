| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the exit checklist completion case? | categorical | exit_checklist_rule | exit_checklist_rule | exit_checklist_rule | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | HR-3001 | HR-3001 | HR-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-10-20T09:30:00 | 2026-10-20T09:30:00 | 2026-10-20T09:47:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Is the exit checklist complete? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the exit-status outcome? | categorical | open | closed | open | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | How many return items are recorded in the core record? | integer | 3 | 2 | 3 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What closure date is recorded in the core record? | date | 2026-10-20 | 2026-10-21 | 2026-10-20 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the exit checklist? | code_set | ['offboarding', 'asset_return'] | ['offboarding', 'asset_return'] | ['offboarding', 'asset_return'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | HR-3001 | HR-3001 | HR-3001 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | exit_checklist_rule | exit_checklist_rule | exit_checklist_rule | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | open | closed | open | flip | invariant | decision_memo#final_status | substantive flip |
