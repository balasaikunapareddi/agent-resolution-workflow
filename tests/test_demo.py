"""Tools + demo: the ADK function tools and the one-command demo."""

from agent_resolution_workflow.demo import run_demo
from agent_resolution_workflow.tools import (
    get_policy,
    lookup_customer_order,
    process_resolution_request,
)


def test_lookup_tool_found(store):
    result = lookup_customer_order("CM-1042")
    assert result["found"] is True
    assert result["customer_email"] == "maya.chen@example.com"


def test_lookup_tool_not_found(store):
    result = lookup_customer_order("CM-9999")
    assert result["found"] is False


def test_policy_tool_found(store):
    result = get_policy("late_delivery")
    assert result["found"] is True
    assert result["allowed_resolutions"] == ["shipping_refund", "store_credit"]


def test_policy_tool_not_found(store):
    assert get_policy("warranty")["found"] is False


def test_workflow_tool_records_and_rejects(store):
    ok = process_resolution_request(
        order_id="CM-1042",
        customer_email="maya.chen@example.com",
        issue_category="damaged_defective",
        requested_resolution="replacement",
        customer_confirmed=True,
        agent_note="Arrived damaged.",
    )
    assert ok["ok"] is True and ok["request_id"] == "RR-0002"
    again = process_resolution_request(
        order_id="CM-1042",
        customer_email="maya.chen@example.com",
        issue_category="damaged_defective",
        requested_resolution="replacement",
        customer_confirmed=True,
        agent_note="Again.",
    )
    assert again["ok"] is False and again["reason"] == "duplicate_pending"


def test_demo_runs_the_scripted_flow_and_records_one_row():
    summary = run_demo(live=False, verbose=False)
    assert len(summary["turns"]) == 3
    assert "recorded for review" in summary["turns"][2]["agent"]
    assert summary["new_request"] is not None
    assert summary["new_request"]["order_id"] == "CM-1042"
    assert summary["new_request"]["requested_resolution"] == "replacement"
    assert summary["new_request"]["status"] == "pending_review"
