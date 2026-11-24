"""agent-resolution-workflow: customer resolution agent + deterministic workflow.

A Google ADK multi-agent system for Northstar Goods support. A coordinator
agent owns the customer conversation and delegates to two sub-agents — the
order agent (read-only order lookup) and the policy agent (policy knowledge
base) — then calls the deterministic ``process_resolution_request`` workflow
to record a resolution request as ``pending_review``. The workflow never
issues refunds, ships replacements, or changes an order.
"""

from .agent import ResolutionAgent
from .workflow import ResolutionRequest, WorkflowResult, process_resolution_request

__all__ = ["ResolutionAgent", "ResolutionRequest", "WorkflowResult", "process_resolution_request"]
