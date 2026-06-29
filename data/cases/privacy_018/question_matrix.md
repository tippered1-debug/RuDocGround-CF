| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which document controls the security incident notification clock case? | categorical | incident_response_policy | incident_response_policy | incident_response_policy | invariant | invariant | policy#controlling_rule | invariant |
| Q2 | What reference number is shown in the nuisance memo? | identifier | INC-1801 | INC-1801 | INC-3301 | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q3 | What timestamp is shown in the nuisance memo? | datetime | 2026-09-12T09:40:00 | 2026-09-12T09:40:00 | 2026-09-12T09:55:00 | invariant | flip | nuisance_memo#timestamp | nuisance check |
| Q4 | Was the notification submitted on time? | boolean | False | True | False | flip | invariant | core_record#substantive_fact | substantive flip |
| Q5 | What is the incident-notice outcome? | categorical | not_timely | timely | not_timely | flip | invariant | decision_memo#final_status | substantive flip |
| Q6 | How many hours remain until the notification deadline in the core record? | integer | 72 | 48 | 72 | flip | invariant | core_record#amount | substantive flip |
| Q7 | What deadline timestamp is recorded in the core record? | datetime | 2026-09-12T10:00:00 | 2026-09-12T06:00:00 | 2026-09-12T10:00:00 | flip | invariant | core_record#deadline_date | substantive flip |
| Q8 | Which control codes apply to the notification clock? | code_set | ['deadline_clock', 'regulator_notice'] | ['deadline_clock', 'regulator_notice'] | ['deadline_clock', 'regulator_notice'] | invariant | invariant | support_note#code_set | invariant |
| Q9 | What identifier is shown in the core record? | identifier | INC-1801 | INC-1801 | INC-1801 | invariant | invariant | core_record#identifier | invariant |
| Q10 | Is the supporting note sufficient? | boolean | True | True | True | invariant | invariant | support_note#support_note_sufficient | invariant |
| Q11 | Is any mandatory supporting document missing? | boolean | False | False | False | invariant | invariant | support_note#missing_information | invariant |
| Q12 | Which authoritative source controls the case? | categorical | incident_response_policy | incident_response_policy | incident_response_policy | invariant | invariant | policy#authoritative_source | invariant |
| Q13 | Did the nuisance memo reference number change in C? | boolean | False | False | True | invariant | flip | nuisance_memo#reference_number | nuisance check |
| Q14 | What is the overall procedural status? | categorical | not_timely | timely | not_timely | flip | invariant | decision_memo#final_status | substantive flip |
