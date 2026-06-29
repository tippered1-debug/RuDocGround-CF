| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Does the escrow agreement allow release after a missed cure deadline? | boolean | False | True | False | flip | invariant | escrow_agreement#release_clause | A no trigger, B trigger met |
| Q2 | Was a valid notice delivered before the cure period started? | boolean | True | True | True | invariant | invariant | notice#delivery | valid notice unchanged |
| Q3 | Did the vendor fail to deliver a working build in A? | boolean | False | False | False | invariant | invariant | support_log#build_status | A no failure |
| Q4 | Did the vendor fail to deliver a working build in B? | boolean | False | True | False | flip | invariant | support_log#build_status | B failure triggers release |
| Q5 | What material is released on trigger? | code_set | source_code_archive+build_scripts | source_code_archive+build_scripts | source_code_archive+build_scripts | invariant | invariant | escrow_agreement#released_materials | scope fixed by escrow clause |
| Q6 | Is customer data part of the release? | boolean | False | False | False | invariant | invariant | escrow_agreement#excluded_materials | excluded by clause |
| Q7 | Does the counsel memo control over the license summary? | boolean | True | True | True | invariant | invariant | counsel_memo#priority | priority fixed |
| Q8 | Has the cure deadline expired in B? | boolean | False | True | False | flip | invariant | support_log#deadline | deadline passed in B |
| Q9 | Does C change the trigger status? | boolean | False | False | True | invariant | flip | license_notice#format_only_change | format nuisance only |
| Q10 | Is the support log the decisive evidence source? | boolean | True | True | True | invariant | invariant | support_log#entries | decisive source |
| Q11 | What is the trigger event category? | categorical | missing_working_build_or_no_cure | missing_working_build_or_no_cure | missing_working_build_or_no_cure | flip | invariant | escrow_agreement#trigger | same trigger type |
| Q12 | Was a separate confirmation required before release? | boolean | True | True | True | invariant | invariant | escrow_agreement#notice_cure_requirement | notice+cure required |
| Q13 | Would the page-number change in C matter? | boolean | False | False | True | invariant | flip | license_notice#page_number | nuisance only |
| Q14 | Is release authorized in A? | boolean | False | True | False | flip | invariant | escrow_agreement#auth | A no trigger |
