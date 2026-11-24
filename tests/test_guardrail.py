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
