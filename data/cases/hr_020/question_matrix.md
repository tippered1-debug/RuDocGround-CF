| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the delegated authority gap case? | categorical | delegation_policy | delegation_policy | delegation_policy | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | DEL-2001 | DEL-2001 | DEL-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-10-01T13:00:00 | 2026-10-01T13:00:00 | 2026-10-01T13:25:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Is the signer authorized for this contract class? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the signature validity outcome? | categorical | unauthorized | authorized | unauthorized | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | What contract class is recorded in the core record? | categorical | maintenance_contracts | purchase_contracts | maintenance_contracts | flip | invariant | core_record#amount | substantive flip |
| Q7 | What delegation date is recorded in the core record? | date | 2026-10-01 | 2026-10-15 | 2026-10-01 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to delegated authority? | code_set | ['authority_scope', 'delegated_signing'] | ['authority_scope', 'delegated_signing'] | ['authority_scope', 'delegated_signing'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | DEL-2001 | DEL-2001 | DEL-2001 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | delegation_policy | delegation_policy | delegation_policy | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | unauthorized | authorized | unauthorized | flip | invariant | decision_memo#final_status | substantive flip |
