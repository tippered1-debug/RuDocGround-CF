| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Which basis is documented in A? | categorical | contract_necessity | consent | contract_necessity | flip | invariant | transfer_assessment#basis | basis unchanged |
| Q2 | Which basis is documented in B? | categorical | consent | consent | consent | flip | invariant | transfer_assessment#basis | basis changed but still documented in B |
| Q3 | Is transfer allowed under the internal policy in A? | boolean | True | True | True | invariant | invariant | policy#allowed_bases | allowed by policy |
| Q4 | Is transfer allowed under the internal policy in B? | boolean | True | False | True | flip | invariant | policy#allowed_bases | B lacks matching consent record |
| Q5 | Does a separate consent record exist for every recipient in B? | boolean | True | False | True | flip | invariant | transfer_assessment#recipient_consents | missing consent in B |
| Q6 | Does the policy fully determine admissibility? | boolean | True | True | True | invariant | invariant | policy#priority | policy controls |
| Q7 | Is external law required to answer the question? | boolean | False | False | False | invariant | invariant | policy#contained | fully internal policy |
| Q8 | Is the department code changed in C? | boolean | False | False | True | invariant | flip | onsite_request#department_code | nuisance metadata only |
| Q9 | Is the transfer path encrypted in all variants? | boolean | True | True | True | invariant | invariant | security_memo#encrypted_channel | unchanged security fact |
| Q10 | Is the processor agreement satisfied if basis is missing? | boolean | False | True | False | flip | invariant | dpa#documented_basis_required | basis required |
| Q11 | What is the final answer type for the transfer decision? | categorical | boolean | boolean | boolean | invariant | invariant | policy#decision_type | structured boolean answer |
| Q12 | Would a changed signature block in C alter admissibility? | boolean | False | False | True | invariant | flip | transfer_assessment#signature_block | nuisance only |
| Q13 | Is the internal policy included in the package? | boolean | True | True | True | invariant | invariant | policy#present | contained in docs |
| Q14 | Does any question require exact-match free text? | boolean | False | False | False | invariant | invariant | all | structured only |
