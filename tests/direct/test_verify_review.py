import json
import sys

import pytest
from conftest import LEADER, VALIDATOR

CONTRACT = "contracts/verify_review.py"

QUALIFIES = "qualifies:meets_all_requirements"
REJECTIONS = [
    "does_not_qualify:not_specific_enough",
    "does_not_qualify:missing_required_evidence",
    "does_not_qualify:unverifiable_claim",
    "does_not_qualify:contradicts_requirements",
]
VALID = [QUALIFIES, *REJECTIONS]
ALL_REASONS = [p.split(":")[1] for p in VALID]
# Every status x reason combination that is NOT one of the five valid pairs.
CROSS_INVALID = [
    f"{s}:{r}"
    for s in ("qualifies", "does_not_qualify")
    for r in ALL_REASONS
    if f"{s}:{r}" not in VALID
]
MALFORMED = [
    "", " ", "qualifies", "does_not_qualify", "meets_all_requirements",
    "qualifies:", ":meets_all_requirements", ":", "qualifies:unknown_reason",
    "unknown:meets_all_requirements", "qualifies::meets_all_requirements",
    "qualifies;meets_all_requirements", "qualifies meets_all_requirements",
    "qualifies : meets_all_requirements", "qualifies: meets_all_requirements",
    "qualifies:meets_all_requirements:extra",
    "qualifies:meets_all_requirements\nextra text",
    "Result: qualifies:meets_all_requirements",
    "qualifies:meets_all_requirements.", '"qualifies:meets_all_requirements"',
    "qualifies:meets_all_requirements does_not_qualify:not_specific_enough",
    "does_not_qualify:not_specific_enough\ndoes_not_qualify:unverifiable_claim",
    "qualifies:meets_all_requirements​", "qualifies :meets_all_requirements",
]


@pytest.fixture
def review(direct_vm, direct_deploy, direct_owner):
    direct_vm.sender = direct_owner
    c = direct_deploy(CONTRACT)
    c.set_requirements(["Must have joined the community", "Must have posted once"])
    c.set_evidence_rules(json.dumps([
        {"requirement": 0, "kind": "subjective"},
        {"requirement": 1, "kind": "subjective"},
    ]))
    return c


def module(c):
    return sys.modules[type(c._instance).__module__]


def leader_says(direct_vm, text):
    direct_vm.mock_llm(r"^\[EqNonComparativeLeader\]", text)


def submit(direct_vm, c, who, claim_id, evidence="joined on 2026-01-01 and posted: hello"):
    direct_vm.sender = who
    c.submit_claim(claim_id, evidence)


def evaluate(direct_vm, c, who, claim_id, leader_text):
    leader_says(direct_vm, leader_text)
    direct_vm.sender = who
    c.evaluate_claim(claim_id)


def assert_pending(c, claim_id):
    got = c.get_claim(claim_id)
    assert got["status"] == "pending" and got["reason"] == ""


# ---------- _normalize_verdict_and_reason (module level) ----------

def test_whitelist_is_exactly_the_five_pairs(review):
    assert set(module(review).VALID_VERDICT_REASON_PAIRS) == set(VALID)
    assert not hasattr(module(review), "VALID_VERDICTS")
    assert not hasattr(module(review), "_normalize_verdict")


def test_normalize_valid_qualifies_pair(review):
    assert module(review)._normalize_verdict_and_reason(QUALIFIES) == QUALIFIES


@pytest.mark.parametrize("pair", REJECTIONS)
def test_normalize_valid_rejection_pairs(review, pair):
    assert module(review)._normalize_verdict_and_reason(pair) == pair


def test_cross_invalid_set_is_the_five_expected(review):
    assert sorted(CROSS_INVALID) == sorted([
        "qualifies:not_specific_enough",
        "qualifies:missing_required_evidence",
        "qualifies:unverifiable_claim",
        "qualifies:contradicts_requirements",
        "does_not_qualify:meets_all_requirements",
    ])


@pytest.mark.parametrize("raw", CROSS_INVALID + MALFORMED)
def test_normalize_rejects_invalid_pairs_and_malformed(review, direct_vm, raw):
    with pytest.raises(module(review).gl.vm.UserError, match="invalid LLM output"):
        module(review)._normalize_verdict_and_reason(raw)


@pytest.mark.parametrize("raw", [None, 1, True, b"qualifies:meets_all_requirements",
                                 ["qualifies:meets_all_requirements"], {"a": 1}])
def test_normalize_rejects_non_str(review, raw):
    with pytest.raises(module(review).gl.vm.UserError, match="invalid LLM output"):
        module(review)._normalize_verdict_and_reason(raw)


@pytest.mark.parametrize("pair", VALID)
def test_normalize_option_a_strips_and_lowercases(review, pair):
    """Decision (Option A): surrounding whitespace and case are normalized,
    the canonical lower-case string is returned and is what gets stored."""
    f = module(review)._normalize_verdict_and_reason
    assert f(f"  {pair.upper()}\n") == pair
    assert f("\t" + pair.title() + " ") == pair


# ---------- evaluate_claim end to end ----------

@pytest.mark.parametrize("pair", VALID)
def test_evaluate_stores_status_and_reason_together(review, direct_vm, direct_alice, pair):
    submit(direct_vm, review, direct_alice, 1)
    evaluate(direct_vm, review, direct_alice, 1, pair)
    status, reason = pair.split(":")
    got = review.get_claim(1)
    assert (got["status"], got["reason"]) == (status, reason)
    assert f"{got['status']}:{got['reason']}" in VALID


def test_evaluate_option_a_noisy_but_valid_output_is_stored_canonical(
        review, direct_vm, direct_alice):
    submit(direct_vm, review, direct_alice, 1)
    evaluate(direct_vm, review, direct_alice, 1, "  Does_Not_Qualify:Unverifiable_Claim \n")
    got = review.get_claim(1)
    assert (got["status"], got["reason"]) == ("does_not_qualify", "unverifiable_claim")


@pytest.mark.parametrize("raw", CROSS_INVALID + MALFORMED[:10])
def test_invalid_llm_output_leaves_claim_pending_with_empty_reason(
        review, direct_vm, direct_alice, raw):
    submit(direct_vm, review, direct_alice, 1)
    leader_says(direct_vm, raw)
    with direct_vm.expect_revert("invalid LLM output"):
        review.evaluate_claim(1)
    assert_pending(review, 1)


def test_failed_evaluation_can_be_retried(review, direct_vm, direct_alice):
    submit(direct_vm, review, direct_alice, 1)
    leader_says(direct_vm, "qualifies:unverifiable_claim")
    with direct_vm.expect_revert("invalid LLM output"):
        review.evaluate_claim(1)
    direct_vm.clear_mocks()
    evaluate(direct_vm, review, direct_alice, 1, REJECTIONS[2])
    assert review.get_claim(1)["reason"] == "unverifiable_claim"


def test_prompt_enumerates_five_strings_and_carries_evidence_and_rules(
        review, direct_vm, direct_alice):
    submit(direct_vm, review, direct_alice, 7, "evidence-marker-123")
    evaluate(direct_vm, review, direct_alice, 7, QUALIFIES)
    prompt = direct_vm.last_prompt
    for pair in VALID:
        assert prompt.count(pair) >= 2  # listed in both the task and the criteria
    assert "EXACTLY ONE" in prompt
    assert "evidence-marker-123" in prompt
    assert "Must have joined the community" in prompt
    assert "separate" not in prompt.lower()  # one combined answer, not verdict + reason


# ---------- get_claim schema ----------

def test_get_claim_includes_reason_field(review, direct_vm, direct_alice):
    submit(direct_vm, review, direct_alice, 1, "some evidence")
    got = review.get_claim(1)
    assert set(got) == {"claimant", "evidence_text", "status", "reason",
                        "results", "commitment", "policy_hash"}
    assert got["evidence_text"] == "some evidence"
    assert got["claimant"] == direct_alice or str(got["claimant"]) == str(direct_alice)


def test_pending_claim_has_empty_reason(review, direct_vm, direct_alice):
    submit(direct_vm, review, direct_alice, 1)
    assert_pending(review, 1)
    got = review.get_claim(1)
    assert got["results"] == "" and got["commitment"] == "" and got["policy_hash"] == ""


def test_get_claim_unknown_id_reverts(review):
    with pytest.raises(Exception, match="claim not found"):
        review.get_claim(99)


# ---------- identity / duplicates / multiple claims ----------

def test_duplicate_claim_id_reverts_and_keeps_first(review, direct_vm, direct_alice, direct_bob):
    submit(direct_vm, review, direct_alice, 1, "first")
    with direct_vm.expect_revert("claim_id already exists"):
        submit(direct_vm, review, direct_bob, 1, "second")
    with direct_vm.expect_revert("claim_id already exists"):
        submit(direct_vm, review, direct_alice, 1, "again")
    got = review.get_claim(1)
    assert got["evidence_text"] == "first"
    assert str(got["claimant"]) == str(direct_alice)


def test_multiple_claims_same_caller_are_independent(review, direct_vm, direct_alice):
    for i in (1, 2, 3):
        submit(direct_vm, review, direct_alice, i, f"evidence {i}")
    evaluate(direct_vm, review, direct_alice, 2, QUALIFIES)
    assert review.get_claim(2)["status"] == "qualifies"
    assert_pending(review, 1)
    assert_pending(review, 3)
    direct_vm.clear_mocks()
    evaluate(direct_vm, review, direct_alice, 3, REJECTIONS[0])
    assert review.get_claim(3)["reason"] == "not_specific_enough"
    assert review.get_claim(2)["reason"] == "meets_all_requirements"
    assert_pending(review, 1)


def test_two_callers_distinct_ids_are_independent(review, direct_vm, direct_alice, direct_bob):
    submit(direct_vm, review, direct_alice, 1, "alice evidence")
    submit(direct_vm, review, direct_bob, 2, "bob evidence")
    assert str(review.get_claim(1)["claimant"]) == str(direct_alice)
    assert str(review.get_claim(2)["claimant"]) == str(direct_bob)


def test_empty_evidence_reverts(review, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("empty evidence"):
        review.submit_claim(1, "")
    with pytest.raises(Exception, match="claim not found"):
        review.get_claim(1)


def test_evaluate_twice_reverts_and_keeps_pair(review, direct_vm, direct_alice):
    submit(direct_vm, review, direct_alice, 1)
    evaluate(direct_vm, review, direct_alice, 1, REJECTIONS[1])
    direct_vm.clear_mocks()
    with direct_vm.expect_revert("already evaluated"):
        review.evaluate_claim(1)
    got = review.get_claim(1)
    assert (got["status"], got["reason"]) == ("does_not_qualify", "missing_required_evidence")


def test_evaluate_unknown_claim_reverts(review, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("claim not found"):
        review.evaluate_claim(5)


def test_anyone_can_evaluate_but_claimant_is_unchanged(
        review, direct_vm, direct_alice, direct_bob):
    submit(direct_vm, review, direct_alice, 1)
    evaluate(direct_vm, review, direct_bob, 1, QUALIFIES)
    assert str(review.get_claim(1)["claimant"]) == str(direct_alice)


# ---------- requirements lifecycle (regression) ----------

def test_evaluate_before_requirements_reverts(direct_vm, direct_deploy, direct_owner, direct_alice):
    direct_vm.sender = direct_owner
    c = direct_deploy(CONTRACT)
    submit(direct_vm, c, direct_alice, 1)
    with direct_vm.expect_revert("requirements not configured yet"):
        c.evaluate_claim(1)
    assert_pending(c, 1)


def test_deploy_needs_no_arguments_and_starts_empty(direct_vm, direct_deploy, direct_owner):
    direct_vm.sender = direct_owner
    c = direct_deploy(CONTRACT)
    assert c.get_requirements() == []


def test_set_requirements_only_organizer_and_only_once(
        direct_vm, direct_deploy, direct_owner, direct_alice):
    direct_vm.sender = direct_owner
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("only the organizer"):
        c.set_requirements(["x"])
    direct_vm.sender = direct_owner
    c.set_requirements(["  x  "])
    assert c.get_requirements() == ["x"]
    with direct_vm.expect_revert("already set"):
        c.set_requirements(["y"])
    assert c.get_requirements() == ["x"]


@pytest.mark.parametrize("bad,msg", [
    ("not a list", "must be a list"),
    (["ok", ""], "non-empty string"),
    (["ok", "   "], "non-empty string"),
    (["ok", 5], "non-empty string"),
    (["a"] * 51, "item limit"),
    (["a" * 1001], "character limit"),
])
def test_set_requirements_validation(direct_vm, direct_deploy, direct_owner, bad, msg):
    direct_vm.sender = direct_owner
    c = direct_deploy(CONTRACT)
    with direct_vm.expect_revert(msg):
        c.set_requirements(bad)
    assert c.get_requirements() == []


@pytest.mark.parametrize("val", [None, []])
def test_set_requirements_none_or_empty_uses_defaults(direct_vm, direct_deploy, direct_owner, val):
    direct_vm.sender = direct_owner
    c = direct_deploy(CONTRACT)
    c.set_requirements(val)
    assert c.get_requirements() == list(module(c).DEFAULT_REQUIREMENTS)


# ---------- validator side (real SDK prompt_non_comparative code path) ----------

def test_validator_accepts_leader_when_llm_validator_agrees(review, direct_vm, direct_alice):
    submit(direct_vm, review, direct_alice, 1)
    evaluate(direct_vm, review, direct_alice, 1, QUALIFIES)
    direct_vm.mock_llm(r"^\[EqNonComparativeValidator\] output='qualifies:meets", "true")
    assert direct_vm.run_validator() is True


def test_validator_rejects_leader_when_llm_validator_disagrees(review, direct_vm, direct_alice):
    submit(direct_vm, review, direct_alice, 1)
    evaluate(direct_vm, review, direct_alice, 1, QUALIFIES)
    direct_vm.mock_llm(r"^\[EqNonComparativeValidator\] output='qualifies:meets", "false")
    assert direct_vm.run_validator() is False


def test_validator_votes_false_on_leader_error(review, direct_vm, direct_alice):
    submit(direct_vm, review, direct_alice, 1)
    evaluate(direct_vm, review, direct_alice, 1, QUALIFIES)
    assert direct_vm.run_validator(leader_error=Exception("boom")) is False


def test_validator_judges_the_leader_output_it_is_given(review, direct_vm, direct_alice):
    """The validator prompt carries the leader's combined string and the same evidence."""
    submit(direct_vm, review, direct_alice, 1, "ev-xyz")
    evaluate(direct_vm, review, direct_alice, 1, QUALIFIES)
    direct_vm.mock_llm(
        r"^\[EqNonComparativeValidator\] output='does_not_qualify:unverifiable_claim'", "false")
    assert direct_vm.run_validator(leader_result="does_not_qualify:unverifiable_claim") is False
    assert "ev-xyz" in direct_vm.last_prompt
    assert "does_not_qualify:unverifiable_claim" in direct_vm.last_prompt


def test_widened_limits_accept_the_new_maximums(direct_vm, direct_deploy, direct_owner):
    direct_vm.sender = direct_owner
    c = direct_deploy(CONTRACT)
    c.set_requirements(["a" * 1000] + ["b"] * 49)
    assert len(c.get_requirements()) == 50
    assert len(c.get_requirements()[0]) == 1000
