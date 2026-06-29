| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | What is the old role end date? | date | 2026-06-11 | 2026-06-11 | 2026-06-11 | invariant | invariant | transfer_order#old_role_end | same in A/B/C |
| Q2 | What is the approval date in A? | date | 2026-06-10 | 2026-06-13 | 2026-06-10 | flip | invariant | access_request#approval_date | same in A |
| Q3 | What is the approval date in B? | date | 2026-06-10 | 2026-06-13 | 2026-06-10 | flip | invariant | access_request#approval_date | B delayed |
| Q4 | Is access valid when granted in A? | boolean | True | True | True | invariant | invariant | iam_log#activation | authorized before role ends |
| Q5 | Is access valid when granted in B? | boolean | True | False | True | flip | invariant | iam_log#activation | approval after role end |
| Q6 | Is there an unauthorized gap in B? | boolean | False | True | False | flip | invariant | role_end_and_approval_gap | B gap exists |
| Q7 | Does manager approval alone override timing? | boolean | False | False | False | invariant | invariant | manager_approval#non_override | manager approval not enough |
| Q8 | Did C change the employee badge number only? | boolean | False | False | True | invariant | flip | account_metadata#badge_number | nuisance only |
| Q9 | Should access be revoked on role end? | boolean | True | True | True | invariant | invariant | hr_memo#revoke_same_day | revocation rule fixed |
| Q10 | What document proves the revocation event? | identifier | iam_log | iam_log | iam_log | invariant | invariant | iam_log#revocation | same source |
| Q11 | Is the new role already active in B? | boolean | False | False | False | invariant | invariant | transfer_order#new_role_start | new role starts later |
| Q12 | Does the access request depend on employment status? | boolean | True | True | True | invariant | invariant | hr_memo#employment_condition | same policy |
| Q13 | Does C alter the access conclusion? | boolean | False | False | True | invariant | flip | account_metadata#badge_number | nuisance only |
| Q14 | Is the time interval between end and approval decisive? | boolean | False | True | False | flip | invariant | gap_length | gap decisive in B |
