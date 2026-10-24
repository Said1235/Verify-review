# Verify Review

Contribution verification for hiring decisions on GenLayer. An employer sets contribution criteria and how each is checked; a candidate submits a statement; the contract records `qualifies` / `does_not_qualify` with a fixed reason code, backed by records that every validator fetches itself.

Flow: `set_requirements([...])` → `set_evidence_rules(<json>)` → `submit_claim` → `evaluate_claim`.
Each criterion is `external` (https record queried with the candidate's wallet + deterministic JSON checks) or `subjective` (LLM on the candidate's text).

```bash
pip install genlayer-test==0.29.2 genvm-linter==0.11.1rc2 cloudpickle pytest
genvm-lint check contracts/verify_review.py
pytest
```
