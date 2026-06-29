| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | What is the controlling temperature range? | categorical | range_2_to_8_celsius | range_2_to_8_celsius | range_2_to_8_celsius | invariant | invariant | temperature_sla#range | controlling threshold |
| Q2 | Was any temperature reading above the allowed maximum? | boolean | False | True | True | flip | invariant | monitoring_log#max_reading | threshold detection |
| Q3 | Did the deviation last more than 30 minutes? | boolean | False | True | True | flip | invariant | monitoring_log#duration_of_excursion | duration check |
| Q4 | Should the party be placed on hold? | boolean | False | True | True | flip | invariant | hold_notice#decision | decision |
| Q5 | Is the shipment eligible for acceptance? | boolean | True | False | False | flip | invariant | acceptance_act#status | decision |
| Q6 | Which document has priority for the temperature rule? | categorical | temperature_sla | temperature_sla | temperature_sla | invariant | invariant | temperature_sla#priority | priority fixed by policy |
| Q7 | What is the documented excursion duration in B? | integer | 0 | 42 | 0 | flip | invariant | monitoring_log#duration_of_excursion | extraction |
| Q8 | Is the complaint itself sufficient to decide acceptance? | boolean | False | False | False | invariant | invariant | complaint#role | complaint supportive only |
| Q9 | Is the route number changed between A and C? | boolean | False | False | True | invariant | flip | delivery_note#route | C nuisance only |
| Q10 | Is the consignee the same in A, B, and C? | boolean | True | True | True | invariant | invariant | delivery_note#consignee | unchanged invariant |
| Q11 | Which status best fits A? | categorical | accepted | held | accepted | flip | invariant | acceptance_act#status | A accepted, B held |
| Q12 | Which status best fits B? | categorical | held | held | held | flip | invariant | acceptance_act#status | B held due to breach |
| Q13 | Does the monitoring log contain the decisive evidence? | boolean | True | True | False | invariant | flip | monitoring_log#readings | decisive evidence source |
| Q14 | Would C change the temperature-based conclusion? | boolean | False | True | False | flip | invariant | all | C nuisance only |
