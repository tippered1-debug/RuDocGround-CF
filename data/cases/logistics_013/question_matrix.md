| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the split shipment acceptance case? | categorical | shipping_procedure | shipping_procedure | shipping_procedure | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | SHIP-1301 | SHIP-1301 | SHIP-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-08-01T11:00:00 | 2026-08-01T11:00:00 | 2026-08-01T11:20:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Is the custody chain complete? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the shipment acceptance outcome? | categorical | partial_acceptance | full_acceptance | partial_acceptance | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | How many custody chains are documented in the core record? | integer | 1 | 2 | 1 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What shipment date is recorded in the core record? | date | 2026-08-01 | 2026-08-02 | 2026-08-01 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the shipment? | code_set | ['warehouse_a', 'warehouse_b'] | ['warehouse_a', 'warehouse_b'] | ['warehouse_a', 'warehouse_b'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | SHIP-1301 | SHIP-1301 | SHIP-1301 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | shipping_procedure | shipping_procedure | shipping_procedure | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | partial_acceptance | full_acceptance | partial_acceptance | flip | invariant | decision_memo#final_status | substantive flip |
