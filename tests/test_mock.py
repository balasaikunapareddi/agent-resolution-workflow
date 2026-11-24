"""The scripted mock LLMs: confirmation detection must not misfire."""

from agent_resolution_workflow.mock_llm import _is_confirmation


def test_confirmation_words():
    assert _is_confirmation("Yes, please go ahead.")
    assert _is_confirmation("Yes.")
    assert _is_confirmation("Sounds good")


def test_negation_is_not_a_confirmation():
    """Review fix: substring matching treated "don't go ahead" as a
    confirmation (it contains "go ahead") — the mock would have recorded
    a request the customer refused."""
    assert not _is_confirmation("No, don't go ahead.")
    assert not _is_confirmation("Do not record it yet.")
    assert not _is_confirmation("Not yet, hold on.")


def test_mentioning_confirm_is_not_a_confirmation():
    """'I need to confirm my address first' contains 'confirm' but is
    not a confirmation of the resolution."""
    assert not _is_confirmation("I need to confirm my address first.")
