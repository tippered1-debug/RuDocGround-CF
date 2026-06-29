| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the partial prepayment threshold case? | categorical | reimbursement_policy | reimbursement_policy | reimbursement_policy | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | PRE-1101 | PRE-1101 | PRE-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-06-01T09:00:00 | 2026-06-01T09:00:00 | 2026-06-01T09:15:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Does the partial prepayment line remain reimbursable? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the decision on the line item? | categorical | rejected | approved | rejected | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | What reimbursable amount is recorded in the core record? | money | 1200 | 0 | 1200 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What deadline date is recorded in the core record? | date | 2026-06-01 | 2026-06-03 | 2026-06-01 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the reimbursement decision? | code_set | ['taxable_scope', 'non_taxable_scope'] | ['taxable_scope', 'non_taxable_scope'] | ['taxable_scope', 'non_taxable_scope'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | INV-1101 | INV-1101 | INV-1101 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | reimbursement_policy | reimbursement_policy | reimbursement_policy | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | rejected | approved | rejected | flip | invariant | decision_memo#final_status | substantive flip |
