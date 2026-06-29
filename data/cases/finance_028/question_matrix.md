| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the advance report substantiation case? | categorical | reimbursement_policy | reimbursement_policy | reimbursement_policy | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | ADV-2801 | ADV-2801 | ADV-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-09-15T08:00:00 | 2026-09-15T08:00:00 | 2026-09-15T08:14:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Is the receipt substantiated? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the reimbursement outcome? | categorical | not_reimbursable | reimbursable | not_reimbursable | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | What reimbursable amount is recorded in the core record? | money | 850 | 0 | 850 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What report date is recorded in the core record? | date | 2026-09-15 | 2026-09-18 | 2026-09-15 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the advance report? | code_set | ['substantiation', 'receipts'] | ['substantiation', 'receipts'] | ['substantiation', 'receipts'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | ADV-2801 | ADV-2801 | ADV-2801 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | reimbursement_policy | reimbursement_policy | reimbursement_policy | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | not_reimbursable | reimbursable | not_reimbursable | flip | invariant | decision_memo#final_status | substantive flip |
