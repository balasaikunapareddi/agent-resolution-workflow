"""The deterministic Process Resolution Request workflow.

This is the predictable half of the system. The conversational agent is
free-form — it can ask, search, and clarify — but recording a resolution
request is a fixed sequence of checks, and it runs here, in code, not in
the model. The workflow NEVER issues a refund, ships a replacement, or
changes an order: its only write is one ``pending_review`` ledger row.

Validation order (first failure wins, with a typed reason):
1. unknown_order — no such order in the store.
2. email_mismatch — the email given does not match the order.
3. confirmation_required — the customer has not confirmed the resolution.
4. unknown_policy — no policy covers the issue category.
5. order_not_eligible — the order is cancelled, or still in transit.
6. resolution_not_allowed — the policy does not allow this resolution.
7. condition_not_met — the policy's condition fails (e.g. a delivery that
   was not at least 5 days late cannot use the late-delivery policy).
8. outside_window — the request is past the policy's day window.
9. duplicate_pending — the same order already has a pending request for
   the same resolution.

``STORE_TODAY`` is the store's reference date for the demo data (the shipped
orders are dated around it). Pass ``today`` explicitly to evaluate against a
different date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .ledger import Ledger
from .orders import Order, find_order
from .policies import Policy, get_policy

STORE_TODAY: date = date(2026, 11, 24)

# Words the customer may use, mapped to the workflow's resolution names.
RESOLUTION_SYNONYMS: dict[str, str] = {
    "replacement": "replacement",
    "replace": "replacement",
    "replace it": "replacement",
    "refund": "refund",
    "money back": "refund",
    "full refund": "refund",
    "store credit": "store_credit",
    "credit": "store_credit",
    "shipping refund": "shipping_refund",
    "refund the shipping": "shipping_refund",
    "refund shipping": "shipping_refund",
    "refund of the shipping": "shipping_refund",
    "shipping cost": "shipping_refund",
}


def normalize_resolution(text: str) -> str | None:
    """Map the customer's words to a resolution name, or None if unknown.

    Longest phrases match first, so "refund of the shipping cost" maps to
    shipping_refund instead of the shorter "refund" inside it.
    """
    lowered = text.strip().lower()
    if lowered in RESOLUTION_SYNONYMS:
        return RESOLUTION_SYNONYMS[lowered]
    for phrase, resolution in sorted(RESOLUTION_SYNONYMS.items(), key=lambda kv: -len(kv[0])):
        if phrase in lowered:
            return resolution
    return None


@dataclass(frozen=True)
class ResolutionRequest:
    """Typed input to the workflow. Every field is required except the note."""

    order_id: str
    customer_email: str
    issue_category: str
    requested_resolution: str
    customer_confirmed: bool
    agent_note: str = ""


@dataclass(frozen=True)
class WorkflowResult:
    """Typed outcome of the workflow: success or a rejection with a reason."""

    ok: bool
    status: str  # recorded | rejected
    reason: str | None  # machine-readable rejection code, None on success
    message: str  # human-readable explanation
    request_id: str | None = None
    record: dict | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status": self.status,
            "reason": self.reason,
            "message": self.message,
            "request_id": self.request_id,
            "record": self.record,
        }


def _days_between(start: str, end: date) -> int | None:
    if not start:
        return None
    return (end - date.fromisoformat(start)).days


def process_resolution_request(
    request: ResolutionRequest,
    ledger: Ledger,
    orders: list[Order] | None = None,
    policies: dict[str, Policy] | None = None,
    today: date = STORE_TODAY,
) -> WorkflowResult:
    """Validate a resolution request and, if valid, record it as pending_review."""
    order = find_order(request.order_id, orders)
    if order is None:
        return WorkflowResult(
            ok=False,
            status="rejected",
            reason="unknown_order",
            message=f"No order {request.order_id.strip().upper()} exists in our records.",
        )
    if request.customer_email.strip().lower() != order.customer_email.lower():
        return WorkflowResult(
            ok=False,
            status="rejected",
            reason="email_mismatch",
            message="The email given does not match the email on this order.",
        )
    if not request.customer_confirmed:
        return WorkflowResult(
            ok=False,
            status="rejected",
            reason="confirmation_required",
            message="The customer has not confirmed this resolution yet.",
        )
    policy = get_policy(request.issue_category, policies)
    if policy is None:
        return WorkflowResult(
            ok=False,
            status="rejected",
            reason="unknown_policy",
            message=f"No support policy covers the issue '{request.issue_category}'.",
        )
    if order.status == "cancelled":
        return WorkflowResult(
            ok=False,
            status="rejected",
            reason="order_not_eligible",
            message=f"Order {order.order_id} was cancelled, so no resolution can be recorded for it.",
        )
    if order.status != "delivered":
        return WorkflowResult(
            ok=False,
            status="rejected",
            reason="order_not_eligible",
            message=f"Order {order.order_id} has not been delivered yet, so no resolution can be recorded for it.",
        )
    resolution = request.requested_resolution.strip().lower()
    if not policy.allows(resolution):
        return WorkflowResult(
            ok=False,
            status="rejected",
            reason="resolution_not_allowed",
            message=(
                f"The {policy.category} policy allows "
                f"{', '.join(policy.allowed_resolutions)} — not {resolution}."
            ),
        )
    if policy.category == "late_delivery":
        days_late = _days_between(order.promised_date, date.fromisoformat(order.delivered_date))
        if days_late is None or days_late < 5:
            return WorkflowResult(
                ok=False,
                status="rejected",
                reason="condition_not_met",
                message=(
                    f"Order {order.order_id} was not at least 5 days late "
                    f"(it was {days_late} days late), so the late-delivery policy does not apply."
                ),
            )
    age = _days_between(order.delivered_date, today)
    if age is not None and age > policy.window_days:
        return WorkflowResult(
            ok=False,
            status="rejected",
            reason="outside_window",
            message=(
                f"Order {order.order_id} was delivered {age} days ago, past the "
                f"{policy.window_days}-day window for the {policy.category} policy."
            ),
        )
    if ledger.find_pending(order.order_id, resolution) is not None:
        return WorkflowResult(
            ok=False,
            status="rejected",
            reason="duplicate_pending",
            message=(
                f"A {resolution} request for order {order.order_id} is already "
                "pending review, so a second one was not recorded."
            ),
        )
    row = ledger.add(
        order_id=order.order_id,
        customer_email=order.customer_email,
        issue_category=policy.category,
        requested_resolution=resolution,
        agent_note=request.agent_note,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    return WorkflowResult(
        ok=True,
        status="recorded",
        reason=None,
        message=(
            f"Recorded {resolution} request {row.request_id} for order {order.order_id} "
            "as pending_review. A human reviews it before anything is sent or refunded."
        ),
        request_id=row.request_id,
        record=row.to_dict(),
    )
