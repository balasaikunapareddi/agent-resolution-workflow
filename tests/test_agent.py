"""The multi-agent loop (mock mode): conversation, memory, rejections."""

from agent_resolution_workflow.agent import FORBIDDEN_CLAIMS

FORBIDDEN = FORBIDDEN_CLAIMS + ("has been sent", "on its way")


def test_scripted_demo_flow_records_one_pending_review(agent, store):
    assert store.ledger.count() == 1  # the seeded prior row only
    reply1 = agent.run("Hi, my order CM-1042 arrived damaged.")
    assert "replacement" in reply1 and "refund" in reply1
    assert store.ledger.count() == 1  # nothing recorded before a choice
    reply2 = agent.run("I would like a replacement.")
    assert "confirm" in reply2.lower()
    assert store.ledger.count() == 1  # nothing recorded before confirmation
    reply3 = agent.run("Yes, please go ahead.")
    assert "recorded for review" in reply3
    assert "RR-0002" in reply3
    assert store.ledger.count() == 2
    row = store.ledger.find_by_order("CM-1042")[0]
    assert row.requested_resolution == "replacement"
    assert row.status == "pending_review"
    assert row.issue_category == "damaged_defective"
    for reply in (reply1, reply2, reply3):
        assert not any(phrase in reply.lower() for phrase in FORBIDDEN)


def test_session_memory_remembers_the_order_across_turns(agent, store):
    agent.run("Hi, my order CM-1042 arrived damaged.")
    # No order id in this message — the agent must still know which order.
    reply = agent.run("I would like a replacement.")
    assert "CM-1042" in reply
    assert "confirm" in reply.lower()


def test_duplicate_request_is_rejected_in_conversation(agent, store):
    agent.run("Hi, my order CM-1042 arrived damaged.")
    agent.run("I would like a replacement.")
    agent.run("Yes, please go ahead.")
    assert store.ledger.count() == 2
    reply = agent.run("Please record another replacement for CM-1042.")
    assert "confirm" in reply.lower()
    reply = agent.run("Yes.")
    assert "already" in reply.lower() or "pending review" in reply.lower()
    assert store.ledger.count() == 2  # no second row


def test_unknown_order_is_not_recorded(agent, store):
    reply = agent.run("Hi, my order CM-9999 arrived damaged.")
    assert "couldn't find" in reply.lower() or "double-check" in reply.lower()
    assert store.ledger.count() == 1


def test_agent_asks_for_the_order_number_when_missing(agent, store):
    reply = agent.run("My package arrived broken.")
    assert "order number" in reply.lower()
    assert store.ledger.count() == 1


def test_unsupported_resolution_is_refused_before_confirmation(agent, store):
    agent.run("Hi, my order CM-1043 arrived late.")
    reply = agent.run("I want a full refund.")
    assert "doesn't allow" in reply.lower() or "not allow" in reply.lower()
    assert "shipping_refund" in reply or "store credit" in reply.lower()
    assert store.ledger.count() == 1


def test_late_delivery_shipping_refund_flow(agent, store):
    agent.run("Hi, my order CM-1043 arrived late.")
    agent.run("I would like a refund of the shipping cost.")
    reply = agent.run("Yes, please go ahead.")
    assert "recorded for review" in reply
    row = store.ledger.find_by_order("CM-1043")[0]
    assert row.requested_resolution == "shipping_refund"
    assert row.status == "pending_review"


def test_new_conversation_forgets_the_previous_order(agent, store):
    agent.run("Hi, my order CM-1042 arrived damaged.")
    agent.new_conversation()
    reply = agent.run("I would like a replacement.")
    assert "order number" in reply.lower()


def test_agent_never_claims_shipment_across_the_full_flow(agent, store):
    replies = [
        agent.run("Hi, my order CM-1042 arrived damaged."),
        agent.run("I would like a replacement."),
        agent.run("Yes, please go ahead."),
    ]
    for reply in replies:
        lowered = reply.lower()
        assert not any(phrase in lowered for phrase in FORBIDDEN)
