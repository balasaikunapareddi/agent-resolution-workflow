"""ADK tools: read-only lookups for the sub-agents, workflow for the coordinator.

The tools read the module-level default store (set by
:class:`~agent_resolution_workflow.agent.ResolutionAgent` at construction,
or by tests). The order and policy tools are read-only; only
``process_resolution_request`` writes, and it writes exactly one
``pending_review`` ledger row after strict validation (see ``workflow.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ledger import Ledger
from .orders import Order, find_order, load_orders
from .policies import Policy, get_policy as _get_policy_record, load_policies
from .workflow import ResolutionRequest, process_resolution_request as _run_workflow

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "resolution_requests.db"


@dataclass
class Store:
    """Everything the tools need: orders, policies, the ledger."""

    orders: list[Order]
    policies: dict[str, Policy]
    ledger: Ledger

    @classmethod
    def load(cls, db_path: Path | str = DEFAULT_DB) -> "Store":
        """Load the shipped store (CSV orders, Markdown policies, SQLite ledger)."""
        return cls(orders=load_orders(), policies=load_policies(), ledger=Ledger(db_path))


_DEFAULT_STORE: Store | None = None


def set_default_store(store: Store | None) -> None:
    """Set the store the tool functions read. Tests swap this per test."""
    global _DEFAULT_STORE
    _DEFAULT_STORE = store


def get_default_store() -> Store:
    """The default store, loading the shipped one on first use."""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = Store.load()
    return _DEFAULT_STORE


def lookup_customer_order(order_id: str) -> dict:
    """Look up a Northstar Goods order by its order id (read-only).

    Args:
        order_id: The order id, e.g. "CM-1042".

    Returns:
        The order's details, or {"found": False} when no such order exists.
    """
    order = find_order(order_id, get_default_store().orders)
    if order is None:
        return {"found": False, "order_id": order_id.strip().upper()}
    return {"found": True, **order.to_dict()}


def get_policy(issue_category: str) -> dict:
    """Read the support policy for an issue category (read-only).

    Args:
        issue_category: One of damaged_defective, late_delivery,
            wrong_item, returns.

    Returns:
        The policy text and its allowed resolutions, or an error when the
        category has no policy.
    """
    policy = _get_policy_record(issue_category, get_default_store().policies)
    if policy is None:
        return {"found": False, "issue_category": issue_category}
    return {
        "found": True,
        "category": policy.category,
        "allowed_resolutions": policy.allowed_resolutions,
        "window_days": policy.window_days,
        "text": policy.text,
    }


def process_resolution_request(
    order_id: str,
    customer_email: str,
    issue_category: str,
    requested_resolution: str,
    customer_confirmed: bool,
    agent_note: str = "",
) -> dict:
    """Record a resolution request as pending_review (deterministic workflow).

    This is the ONLY write in the system. It validates the request against
    the order and the policy and writes one pending_review ledger row — it
    never issues a refund, ships a replacement, or changes an order. Call
    it only after the customer has confirmed the resolution they want.

    Args:
        order_id: The order id, e.g. "CM-1042".
        customer_email: The email on the order.
        issue_category: One of damaged_defective, late_delivery,
            wrong_item, returns.
        requested_resolution: One of replacement, refund, store_credit,
            shipping_refund.
        customer_confirmed: True only when the customer has confirmed
            this resolution in this conversation.
        agent_note: Short note describing the customer's problem.

    Returns:
        {"ok": true, "status": "recorded", "request_id": ...} on success,
        or {"ok": false, "status": "rejected", "reason": ...} on rejection.
    """
    store = get_default_store()
    result = _run_workflow(
        ResolutionRequest(
            order_id=order_id,
            customer_email=customer_email,
            issue_category=issue_category,
            requested_resolution=requested_resolution,
            customer_confirmed=customer_confirmed,
            agent_note=agent_note,
        ),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
    )
    return result.to_dict()
