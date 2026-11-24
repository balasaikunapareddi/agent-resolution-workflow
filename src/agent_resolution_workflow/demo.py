"""One-command demo: the CM-1042 damaged-order conversation, end to end.

Scripted turns (mock by default, ``--live`` for Gemini):
1. "My order CM-1042 arrived damaged." — the agent looks the order up and
   checks the damaged/defective policy.
2. "I would like a replacement." — the agent confirms a replacement is
   supported and asks for confirmation.
3. "Yes, please go ahead." — the agent calls the workflow, which records a
   pending_review row; the agent confirms it was recorded for review.

Run: ``python -m agent_resolution_workflow demo`` (or ``--live``).
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from .agent import ResolutionAgent
from .orders import load_orders
from .policies import load_policies
from .ledger import Ledger
from .tools import Store

SCRIPTED_TURNS = [
    "Hi, my order CM-1042 arrived damaged.",
    "I would like a replacement.",
    "Yes, please go ahead.",
]


def fresh_demo_store() -> Store:
    """A store with a throwaway ledger, so the demo is repeatable.

    The ledger is still seeded with the one prior row from
    data/resolution_requests.csv, so the demo shows RR-0001 already pending
    and records the new request as RR-0002.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return Store(orders=load_orders(), policies=load_policies(), ledger=Ledger(tmp.name))


def run_demo(live: bool = False, store: Store | None = None, verbose: bool = True) -> dict:
    """Run the scripted conversation; return a summary dict for tests."""
    agent = ResolutionAgent(live=live, store=store or fresh_demo_store())
    turns: list[dict] = []
    if verbose:
        print("Northstar Goods — customer resolution demo")
        print("=" * 60)
    for message in SCRIPTED_TURNS:
        reply = agent.run(message)
        turns.append({"customer": message, "agent": reply})
        if verbose:
            print(f"\nCUSTOMER: {message}")
            print(f"AGENT: {reply}")
    rows = agent.ledger_rows()
    new_rows = [r for r in rows if r["order_id"] == "CM-1042"]
    summary = {
        "turns": turns,
        "ledger_rows": rows,
        "new_request": new_rows[-1] if new_rows else None,
    }
    if verbose:
        print("\n" + "-" * 60)
        print("LEDGER (resolution_requests):")
        for row in rows:
            print(
                f"  {row['request_id']} | {row['order_id']} | "
                f"{row['requested_resolution']} | {row['status']} | {row['issue_category']}"
            )
        if summary["new_request"]:
            print(
                f"\nRecorded {summary['new_request']['request_id']} for CM-1042 "
                f"({summary['new_request']['requested_resolution']}) — pending_review."
            )
            print("Nothing was shipped and nothing was refunded. A human reviews it first.")
    return summary


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the demo."""
    parser = argparse.ArgumentParser(description="Run the CM-1042 resolution demo.")
    parser.add_argument("--live", action="store_true", help="Use live Gemini instead of the scripted mock.")
    args = parser.parse_args(argv)
    run_demo(live=args.live)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
