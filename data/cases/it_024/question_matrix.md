| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the escalation path breach case? | categorical | escalation_matrix | escalation_matrix | escalation_matrix | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | TKT-2401 | TKT-2401 | TKT-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-12-01T08:30:00 | 2026-12-01T08:30:00 | 2026-12-01T08:44:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Was the escalation routed to the correct tier? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the escalation compliance outcome? | categorical | non_compliant | compliant | non_compliant | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | What escalation tier is recorded in the core record? | integer | 2 | 3 | 2 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What ticket date is recorded in the core record? | date | 2026-12-01 | 2026-12-02 | 2026-12-01 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the escalation matrix? | code_set | ['tier_check', 'sla_clock'] | ['tier_check', 'sla_clock'] | ['tier_check', 'sla_clock'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | TKT-2401 | TKT-2401 | TKT-2401 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | escalation_matrix | escalation_matrix | escalation_matrix | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | non_compliant | compliant | non_compliant | flip | invariant | decision_memo#final_status | substantive flip |
