"""The deterministic workflow: every validation rule, plus the happy paths."""

from datetime import date

from agent_resolution_workflow.orders import Order
from agent_resolution_workflow.workflow import (
    ResolutionRequest,
    normalize_resolution,
    process_resolution_request,
)

TODAY = date(2026, 11, 24)


def req(order_id, email, category, resolution, confirmed=True, note=""):
    return ResolutionRequest(
        order_id=order_id,
        customer_email=email,
        issue_category=category,
        requested_resolution=resolution,
        customer_confirmed=confirmed,
        agent_note=note,
    )


def test_happy_path_replacement_for_damaged_order(store):
    result = process_resolution_request(
        req("CM-1042", "maya.chen@example.com", "damaged_defective", "replacement"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert result.ok and result.status == "recorded"
    assert result.request_id == "RR-0002"  # RR-0001 is the seeded prior row
    assert result.record["status"] == "pending_review"
    assert result.record["order_id"] == "CM-1042"
    assert store.ledger.count() == 2


def test_happy_path_refund_for_damaged_order(store):
    result = process_resolution_request(
        req("CM-1046", "sara.kim@example.com", "damaged_defective", "refund"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert result.ok and result.request_id == "RR-0002"


def test_rejects_unknown_order(store):
    result = process_resolution_request(
        req("CM-9999", "nobody@example.com", "damaged_defective", "replacement"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert not result.ok and result.reason == "unknown_order"
    assert store.ledger.count() == 1


def test_rejects_email_mismatch(store):
    result = process_resolution_request(
        req("CM-1042", "someone-else@example.com", "damaged_defective", "replacement"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert not result.ok and result.reason == "email_mismatch"
    assert store.ledger.count() == 1


def test_rejects_missing_confirmation(store):
    result = process_resolution_request(
        req("CM-1042", "maya.chen@example.com", "damaged_defective", "replacement", confirmed=False),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert not result.ok and result.reason == "confirmation_required"
    assert store.ledger.count() == 1


def test_rejects_unknown_policy(store):
    result = process_resolution_request(
        req("CM-1042", "maya.chen@example.com", "warranty", "replacement"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert not result.ok and result.reason == "unknown_policy"


def test_rejects_cancelled_order(store):
    result = process_resolution_request(
        req("CM-1049", "james.park@example.com", "returns", "refund"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert not result.ok and result.reason == "order_not_eligible"


def test_rejects_order_still_in_transit(store):
    result = process_resolution_request(
        req("CM-1047", "alex.rivera@example.com", "returns", "refund"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert not result.ok and result.reason == "order_not_eligible"


def test_rejects_resolution_the_policy_does_not_allow(store):
    # Late delivery allows shipping_refund / store_credit — not a full refund.
    result = process_resolution_request(
        req("CM-1043", "daniel.okafor@example.com", "late_delivery", "refund"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert not result.ok and result.reason == "resolution_not_allowed"
    assert "shipping_refund" in result.message


def test_rejects_late_delivery_that_was_not_5_days_late(store):
    barely_late = Order(
        order_id="CM-2000",
        customer_name="Test Customer",
        customer_email="test@example.com",
        item="Test Item",
        item_price=10.0,
        status="delivered",
        order_date="2026-11-08",
        promised_date="2026-11-10",
        delivered_date="2026-11-12",  # only 2 days late
    )
    result = process_resolution_request(
        req("CM-2000", "test@example.com", "late_delivery", "shipping_refund"),
        ledger=store.ledger,
        orders=store.orders + [barely_late],
        policies=store.policies,
        today=TODAY,
    )
    assert not result.ok and result.reason == "condition_not_met"


def test_rejects_request_past_the_30_day_window(store):
    # CM-1045 was delivered 2026-10-05 — 50 days before the reference date.
    result = process_resolution_request(
        req("CM-1045", "tom.becker@example.com", "damaged_defective", "replacement"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert not result.ok and result.reason == "outside_window"


def test_rejects_duplicate_pending_request(store):
    first = process_resolution_request(
        req("CM-1042", "maya.chen@example.com", "damaged_defective", "replacement"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert first.ok
    second = process_resolution_request(
        req("CM-1042", "maya.chen@example.com", "damaged_defective", "replacement"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert not second.ok and second.reason == "duplicate_pending"
    assert store.ledger.count() == 2  # seed + first only


def test_different_resolution_for_same_order_is_not_a_duplicate(store):
    first = process_resolution_request(
        req("CM-1042", "maya.chen@example.com", "damaged_defective", "replacement"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    second = process_resolution_request(
        req("CM-1042", "maya.chen@example.com", "damaged_defective", "refund"),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
        today=TODAY,
    )
    assert first.ok and second.ok
    assert store.ledger.count() == 3


def test_normalize_resolution_synonyms():
    assert normalize_resolution("I would like a replacement") == "replacement"
    assert normalize_resolution("Please replace it") == "replacement"
    assert normalize_resolution("I want my money back") == "refund"
    assert normalize_resolution("store credit please") == "store_credit"
    assert normalize_resolution("refund the shipping") == "shipping_refund"
    assert normalize_resolution("I would like a refund of the shipping cost.") == "shipping_refund"
    assert normalize_resolution("send me a unicorn") is None
