"""Policy knowledge base: Markdown files are the source of truth."""

import pytest

from agent_resolution_workflow.policies import (
    find_policy_for,
    get_policy,
    load_policies,
)

EXPECTED = {
    "damaged_defective": ["replacement", "refund"],
    "late_delivery": ["shipping_refund", "store_credit"],
    "wrong_item": ["replacement", "refund"],
    "returns": ["refund", "store_credit"],
}


def test_loads_all_four_policies():
    policies = load_policies()
    assert set(policies) == set(EXPECTED)


@pytest.mark.parametrize("category,allowed", EXPECTED.items())
def test_allowed_resolutions_come_from_the_markdown(category, allowed):
    assert load_policies()[category].allowed_resolutions == allowed


def test_each_policy_has_a_30_day_window():
    for policy in load_policies().values():
        assert policy.window_days == 30
        assert policy.text  # the agent reads the prose, not just headers


def test_get_unknown_policy_returns_none():
    assert get_policy("warranty") is None


def test_find_policy_for_damaged_words():
    assert find_policy_for("My order arrived damaged and broken.").category == "damaged_defective"


def test_find_policy_for_late_words():
    assert find_policy_for("It arrived really late, days after it was promised.").category == "late_delivery"


def test_find_policy_for_wrong_item_words():
    assert find_policy_for("I got the wrong item, not what I ordered.").category == "wrong_item"


def test_find_policy_for_return_words():
    assert find_policy_for("I want to return it, I changed my mind.").category == "returns"


def test_find_policy_for_unrelated_words_returns_none():
    assert find_policy_for("What are your opening hours?") is None
