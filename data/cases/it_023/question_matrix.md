| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the sla penalty waiver case? | categorical | sla_policy | sla_policy | sla_policy | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | SLA-2301 | SLA-2301 | SLA-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-11-10T15:00:00 | 2026-11-10T15:00:00 | 2026-11-10T15:20:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Is the service credit waived? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the service-credit outcome? | categorical | not_waived | waived | not_waived | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | What service credit amount is recorded in the core record? | money | 50000 | 0 | 50000 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What report timestamp is recorded in the core record? | datetime | 2026-11-10T16:00:00 | 2026-11-10T18:00:00 | 2026-11-10T16:00:00 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the SLA file? | code_set | ['waiver_clause', 'service_credit'] | ['waiver_clause', 'service_credit'] | ['waiver_clause', 'service_credit'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | SLA-2301 | SLA-2301 | SLA-2301 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | sla_policy | sla_policy | sla_policy | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | not_waived | waived | not_waived | flip | invariant | decision_memo#final_status | substantive flip |
