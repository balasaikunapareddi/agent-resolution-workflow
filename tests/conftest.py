"""Shared fixtures: a fresh store per test (temp SQLite ledger, seeded)."""

from __future__ import annotations

import pytest

from agent_resolution_workflow.agent import ResolutionAgent
from agent_resolution_workflow.ledger import Ledger
from agent_resolution_workflow.orders import load_orders
from agent_resolution_workflow.policies import load_policies
from agent_resolution_workflow.tools import Store, set_default_store
from agent_resolution_workflow.workflow import STORE_TODAY


@pytest.fixture()
def store(tmp_path):
    """A store with the shipped orders/policies and a throwaway ledger.

    The ledger is seeded from data/resolution_requests.csv, so it starts
    with the one prior row (RR-0001, CM-1048, store_credit, pending_review).

    The reference date is pinned to STORE_TODAY so the 30-day window
    checks are reproducible whenever the suite runs; the real-date
    default is covered separately in test_workflow.py.
    """
    ledger = Ledger(tmp_path / "test.db")
    value = Store(orders=load_orders(), policies=load_policies(),
                  ledger=ledger, today=STORE_TODAY)
    set_default_store(value)
    yield value
    ledger.close()


@pytest.fixture()
def agent(store):
    """A mock-mode ResolutionAgent wired to the fixture store."""
    return ResolutionAgent(live=False, store=store)
