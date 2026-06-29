| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which source is authoritative for vendor status? | categorical | registry | registry | registry | invariant | invariant | registry#authoritative | registry controls |
| Q2 | What is the check date? | datetime | 2026-06-20T10:00:00 | 2026-06-20T10:00:00 | 2026-06-20T10:00:00 | invariant | invariant | approval_sheet#check_date | same check date |
| Q3 | Is the vendor compliant in A? | boolean | True | False | True | flip | invariant | registry#status | A aligned |
| Q4 | Is the vendor compliant in B? | boolean | True | False | True | flip | invariant | registry#status | B blocked |
| Q5 | Does the certificate alone determine eligibility? | boolean | False | False | False | invariant | invariant | policy#certificate_not_enough | registry required |
| Q6 | Does the conflict require escalation? | boolean | False | True | False | flip | invariant | conflict_policy#escalation | B conflict triggers escalation |
| Q7 | Is the certificate current in A? | boolean | True | True | True | invariant | invariant | certificate#current | same in A |
| Q8 | Does C only change contact email/footer text? | boolean | False | False | True | invariant | flip | certificate#format_metadata | nuisance only |
| Q9 | Would the registry status override the certificate? | boolean | True | True | True | invariant | invariant | registry#override | registry controlling |
| Q10 | Is one document sufficient if the registry is blocked? | boolean | False | False | False | invariant | invariant | policy#insufficient_certificate | one doc insufficient |
| Q11 | What is the effect of a blocked registry on eligibility? | categorical | ineligible | ineligible | ineligible | flip | invariant | registry#blocked_effect | same effect |
| Q12 | Does the approval sheet record the controlling source? | boolean | True | True | True | invariant | invariant | approval_sheet#source_recorded | same record |
| Q13 | Could the case be solved from the certificate alone? | boolean | False | True | False | flip | invariant | certificate_only_insufficient | needs registry |
| Q14 | Is the C variant a pure numeric/name reskin? | boolean | False | False | True | invariant | flip | all | nuisance only |
