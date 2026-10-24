# Verify Review

A [GenLayer](https://www.genlayer.com) intelligent contract that verifies a candidate's claimed contributions for hiring decisions.

An employer defines the contribution criteria it cares about and how each one is checked. A candidate submits a statement. The contract then records a categorical verdict with a fixed reason code. Contributions that can be checked against a public record are checked against that record, not taken from the candidate's text.

The contract handles no funds, tokens or personal documents. It only produces a verdict; what happens next (interview, hiring, payment) is up to another system.

## How it works

1. **Criteria.** The employer (the deploying wallet) calls `set_requirements` once with a list of criteria, for example "Has merged pull requests in the project".
2. **Evidence rules.** The employer calls `set_evidence_rules` once and declares every criterion as either:
   - `external`: an `https` record queried with the candidate's wallet, plus deterministic checks on the JSON it returns;
   - `subjective`: a qualitative criterion judged by an LLM from the candidate's statement.
3. **Submission.** A candidate calls `submit_claim(claim_id, evidence_text)`. The candidate's wallet is taken from the transaction sender.
4. **Review.** Anyone can call `evaluate_claim(claim_id)`:
   - The leader and every validator each fetch the `external` records themselves and must derive an identical result: a status per criterion plus a hash of the exact fields that were checked.
   - The verdict is then derived from those results. A candidate cannot qualify while an `external` criterion is missing or contradicted.
   - The LLM runs only for `subjective` criteria, and only if every `external` criterion was verified. It never sees the fetched documents.
   - If a source is unreachable, returns an error, or returns malformed data, the review aborts and nothing is stored. It can be retried.

## Verdicts

Every stored outcome is exactly one of these strings (`status:reason`):

| Verdict | Meaning |
|---|---|
| `qualifies:meets_all_requirements` | Every criterion is verified |
| `does_not_qualify:missing_required_evidence` | An external record or field was not found |
| `does_not_qualify:contradicts_requirements` | A record exists but shows something else (wrong person, wrong status, below threshold) |
| `does_not_qualify:not_specific_enough` | Subjective stage: the statement is too vague |
| `does_not_qualify:unverifiable_claim` | Subjective stage: the claim cannot be established |

## Rule format

`set_evidence_rules` takes a JSON string: a list with exactly one object per criterion, in any order.

```json
[
  {
    "requirement": 0,
    "kind": "external",
    "url": "https://api.example.org/members/{claimant}",
    "checks": [
      { "path": "member.wallet", "op": "eq_ci", "value": "{claimant}" },
      { "path": "member.status", "op": "eq", "value": "active" }
    ],
    "missing_status": [404]
  },
  { "requirement": 1, "kind": "subjective" }
]
```

- `{claimant}` is replaced with the candidate's lower-case wallet address. Every `external` rule must use it, in the URL or as an `eq`/`eq_ci` check value, so the record is tied to the candidate. Candidates never supply URLs.
- Sources must be `https` URLs on a public DNS host. IP addresses, `localhost`, `*.local`, credentials in the URL and fragments are rejected.
- Checks use a dotted JSON path (array indexes allowed) and one of: `exists`, `eq` (type-strict), `eq_ci` (case-insensitive string), `gte` (integer).
- `missing_status` lists up to three HTTP 4xx codes that mean "no such record" (for example `404`). Any other non-200 response aborts the review.

The host `example.org` above is a placeholder. The contract ships with no built-in data source: choosing a source that is genuinely authoritative for each criterion is the employer's decision.

## Methods

| Method | Type | Notes |
|---|---|---|
| `set_requirements(requirements)` | write | Organizer only, once |
| `set_evidence_rules(rules_json)` | write | Organizer only, once, after the criteria |
| `submit_claim(claim_id, evidence_text)` | write | Caller-chosen `claim_id`; duplicates revert |
| `evaluate_claim(claim_id)` | write | Requires criteria and rules; only for pending claims |
| `get_requirements()` | view | |
| `get_evidence_rules()` | view | |
| `get_claim(claim_id)` | view | `claimant`, `evidence_text`, `status`, `reason`, `results`, `commitment`, `policy_hash` |

The constructor takes no arguments, so the contract deploys without any data.

## Limits

Up to 50 criteria of 1000 characters each; up to 10 checks per rule; URLs up to 600 characters; rules JSON up to 100,000 characters; source responses up to 1 MB.

## Development

```bash
pip install genlayer-test==0.29.2 genvm-linter==0.11.1rc2 cloudpickle pytest
genvm-lint check contracts/verify_review.py
pytest
```

Tests run in GenLayer Direct Mode with mocked web data and a mocked LLM backend (a small shim in `tests/direct/conftest.py`, because Direct Mode does not implement the prompt-template call). They cover identity mismatch, wrong or missing records, source failures, malformed data, validator disagreement, prompt injection and verdict consistency.

## Known limitations

- The contract validates a source's form and its binding to the candidate, not whether the host is trustworthy. A source anyone can edit is not authoritative, even over `https`.
- A criterion declared `subjective` is judged from the candidate's text only.
- Rules cannot express time windows, search arrays, send credentials or paginate; use per-wallet endpoints that expose a scalar field.
- Sources can change between the leader's and the validators' requests. A mismatch causes disagreement and a retry, never acceptance.
- Direct Mode tests do not replace a run on GenLayer Studio, which has not been done for this version.
