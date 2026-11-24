"""Live test: the full CM-1042 conversation against real Gemini (ADK + LiteLLM).

Run via the harness (injects GEMINI_API_KEY):
    python3 ~/workspace/custom-connectors/custom.gemini/bin/run_live.py \
        ~/workspace/agent-resolution-workflow .venv/bin/python scripts/live_test.py

Asserts, all against the live run:
1. Turn 1 (damaged CM-1042): the agent's reply names the resolutions the
   damaged/defective policy allows (replacement, refund) — i.e. it actually
   consulted the order and policy sub-agents.
2. Turn 2 (chooses replacement): the agent asks for confirmation and does
   NOT record anything yet (ledger unchanged).
3. Turn 3 (confirms): the workflow records exactly one pending_review row
   for CM-1042/replacement, and the final reply says "recorded for review"
   without claiming anything was sent, shipped, or refunded.
4. Rejection via conversation: asking for the same replacement again and
   confirming is rejected as a duplicate — ledger unchanged, reply explains.
5. Rejection at the workflow: a full refund for late-delivery order CM-1043
   is rejected with reason resolution_not_allowed (direct call).

Writes .runs/live/attempt-N/report.json and prints [live] lines.
Exits non-zero on the first failed assertion.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_resolution_workflow.agent import (
    ResolutionAgent,
    contains_forbidden_claim,
)
from agent_resolution_workflow.demo import fresh_demo_store
from agent_resolution_workflow.workflow import ResolutionRequest, process_resolution_request

REPO = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO / ".runs" / "live"


def check(condition: bool, label: str, detail: str = "") -> None:
    """Assert with a printed [live] line; exit non-zero on failure."""
    status = "OK  " if condition else "FAIL"
    print(f"[live] {status} {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        raise SystemExit(f"LIVE TEST FAILED: {label} {detail}")


def main() -> int:
    store = fresh_demo_store()
    assert store.ledger.count() == 1, "seed row missing"
    agent = ResolutionAgent(live=True, store=store)
    report: dict = {"turns": [], "checks": {}}
    t0 = time.time()

    # Turn 1 — problem statement. The agent must consult order + policy.
    reply1 = agent.run("Hi, my order CM-1042 arrived damaged.")
    report["turns"].append({"customer": "Hi, my order CM-1042 arrived damaged.", "agent": reply1})
    print(f"[live] turn 1 reply: {reply1}")
    check("replacement" in reply1.lower(), "turn 1 names replacement as an option", reply1[:160])
    check("refund" in reply1.lower(), "turn 1 names refund as an option", reply1[:160])
    check(store.ledger.count() == 1, "turn 1 records nothing", f"ledger={store.ledger.count()}")

    # Turn 2 — chooses a resolution. Must ask for confirmation, record nothing.
    # The confirmation question can be phrased many ways ("is that correct?",
    # "shall I record it?") — accept any of them, not just the word "confirm":
    # an earlier live run failed here only because the model asked "is that
    # correct?" instead of using the word "confirm".
    reply2 = agent.run("I would like a replacement.")
    report["turns"].append({"customer": "I would like a replacement.", "agent": reply2})
    print(f"[live] turn 2 reply: {reply2}")
    confirm_phrases = ("confirm", "is that correct", "is this correct",
                       "shall i", "would you like me to", "should i go ahead",
                       "go ahead?")
    check(any(p in reply2.lower() for p in confirm_phrases),
          "turn 2 asks for confirmation", reply2[:160])
    check(store.ledger.count() == 1, "turn 2 records nothing before confirmation", f"ledger={store.ledger.count()}")

    # Turn 3 — confirms. The workflow must record exactly one pending row.
    reply3 = agent.run("Yes, please go ahead.")
    report["turns"].append({"customer": "Yes, please go ahead.", "agent": reply3})
    print(f"[live] turn 3 reply: {reply3}")
    check(store.ledger.count() == 2, "turn 3 records exactly one row", f"ledger={store.ledger.count()}")
    rows = store.ledger.find_by_order("CM-1042")
    check(len(rows) == 1, "exactly one CM-1042 row", f"rows={len(rows)}")
    row = rows[0]
    check(row.requested_resolution == "replacement", "row is a replacement", row.requested_resolution)
    check(row.status == "pending_review", "row is pending_review", row.status)
    check(row.issue_category == "damaged_defective", "row category is damaged_defective", row.issue_category)
    check("recorded for review" in reply3.lower(), "turn 3 says recorded for review", reply3[:200])
    check(row.request_id in reply3, "turn 3 cites the request id", reply3[:200])
    check(
        not contains_forbidden_claim(reply3),
        "turn 3 never claims shipment/refund",
        reply3[:200],
    )

    # Rejection A — duplicate, via conversation. The agent may spot the
    # duplicate itself in turn 4 (it remembers RR-0002 from the history) or
    # ask for confirmation and be rejected by the workflow in turn 5.
    # Either path must end with the duplicate explained and no new row.
    reply4 = agent.run("Please record another replacement for CM-1042.")
    report["turns"].append({"customer": "Please record another replacement for CM-1042.", "agent": reply4})
    print(f"[live] turn 4 reply: {reply4}")
    duplicate_reply = reply4
    if "already" not in reply4.lower() and "pending review" not in reply4.lower():
        reply5 = agent.run("Yes.")
        report["turns"].append({"customer": "Yes.", "agent": reply5})
        print(f"[live] turn 5 reply: {reply5}")
        duplicate_reply = reply5
    check(store.ledger.count() == 2, "duplicate request adds no row", f"ledger={store.ledger.count()}")
    check(
        "already" in duplicate_reply.lower() or "pending review" in duplicate_reply.lower(),
        "duplicate reply explains it is already pending",
        duplicate_reply[:200],
    )

    # Rejection B — unsupported resolution, direct workflow call.
    result = process_resolution_request(
        ResolutionRequest(
            order_id="CM-1043",
            customer_email="daniel.okafor@example.com",
            issue_category="late_delivery",
            requested_resolution="refund",
            customer_confirmed=True,
            agent_note="Live test rejection case.",
        ),
        ledger=store.ledger,
        orders=store.orders,
        policies=store.policies,
    )
    print(f"[live] workflow rejection B: {result.to_dict()}")
    check(not result.ok and result.reason == "resolution_not_allowed", "full refund for late delivery rejected")

    report["ledger_rows"] = [r.to_dict() for r in store.ledger.all()]
    report["elapsed_s"] = round(time.time() - t0, 1)
    report["checks"] = {"happy_path": True, "duplicate_rejected": True, "unsupported_rejected": True}

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    attempt = len(list(RUNS_DIR.glob("attempt-*/report.json"))) + 1
    out_dir = RUNS_DIR / f"attempt-{attempt}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[live] saved {out_dir / 'report.json'}")
    print(f"[live] LIVE TEST PASSED in {report['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
