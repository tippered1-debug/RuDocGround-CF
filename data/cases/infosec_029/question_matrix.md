| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the privileged account emergency use case? | categorical | privileged_access_policy | privileged_access_policy | privileged_access_policy | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | ACC-2901 | ACC-2901 | ACC-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-11-20T15:00:00 | 2026-11-20T15:00:00 | 2026-11-20T15:25:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Is the emergency access session still valid? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the access-validity outcome? | categorical | expired | valid | expired | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | What expiry timestamp is recorded in the core record? | datetime | 2026-11-20T18:00:00 | 2026-11-20T17:00:00 | 2026-11-20T18:00:00 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What approval timestamp is recorded in the core record? | datetime | 2026-11-20T16:00:00 | 2026-11-20T16:15:00 | 2026-11-20T16:00:00 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to privileged access? | code_set | ['emergency_access', 'post_review'] | ['emergency_access', 'post_review'] | ['emergency_access', 'post_review'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | ACC-2901 | ACC-2901 | ACC-2901 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | privileged_access_policy | privileged_access_policy | privileged_access_policy | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | expired | valid | expired | flip | invariant | decision_memo#final_status | substantive flip |
