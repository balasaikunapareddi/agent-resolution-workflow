"""The reply guardrail: a recorded request is never announced as shipped."""

from agent_resolution_workflow.agent import guard_reply


def test_good_reply_after_recording_passes_through():
    reply = (
        "Your replacement request for order CM-1042 has been recorded for "
        "review — request RR-0002."
    )
    assert guard_reply(reply, record_created=True, request_id="RR-0002") == reply


def test_reply_claiming_shipment_is_replaced():
    reply = "Good news — your replacement has been sent and is on its way!"
    fixed = guard_reply(reply, record_created=True, request_id="RR-0002")
    assert "recorded for review" in fixed
    assert "RR-0002" in fixed
    assert "has been sent" not in fixed
    assert "on its way" not in fixed


def test_reply_claiming_refund_is_replaced():
    reply = "Your refund has been issued to your card."
    fixed = guard_reply(reply, record_created=True)
    assert "recorded for review" in fixed
    assert "issued" not in fixed


def test_reply_missing_the_recorded_phrase_is_replaced():
    reply = "All sorted, thanks for your patience!"
    fixed = guard_reply(reply, record_created=True, request_id="RR-0002")
    assert "recorded for review" in fixed
    assert "RR-0002" in fixed


def test_bad_claim_without_a_record_is_replaced_too():
    reply = "We've shipped your replacement already."
    fixed = guard_reply(reply, record_created=False)
    assert "pending review" in fixed
    assert "shipped" not in fixed


def test_ordinary_reply_without_a_record_passes_through():
    reply = "Could you share your order number so I can look it up?"
    assert guard_reply(reply, record_created=False) == reply


def test_paraphrased_false_claims_are_caught_without_a_record():
    """Review fix: the guardrail listed ten exact phrases, so a live model
    could paraphrase around it. These all passed through unchanged before
    the fix — each claims money or goods moved with nothing recorded."""
    for reply in (
        "Your refund is on its way to your card.",
        "We've sent your replacement already.",
        "The credit has been added to your account.",
        "Your replacement is being prepared and will ship soon.",
        "Good news, your refund was processed this morning.",
    ):
        fixed = guard_reply(reply, record_created=False)
        assert "pending review" in fixed, reply
        # The original false claim is gone (the safe text itself says
        # "nothing has been sent", so check the claim's wording, not the
        # word "sent").
        assert reply.lower() not in fixed.lower(), reply
        assert "on its way to your card" not in fixed.lower(), reply
        assert "will ship soon" not in fixed.lower(), reply


def test_legitimate_recorded_reply_still_passes_through():
    reply = (
        "Thanks for confirming. Your replacement request for order CM-1042 "
        "has been recorded for review — request RR-0002. A human reviews it "
        "before anything is sent or refunded."
    )
    assert guard_reply(reply, record_created=True, request_id="RR-0002") == reply
