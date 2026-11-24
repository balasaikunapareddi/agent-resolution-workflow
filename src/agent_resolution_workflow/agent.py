"""The multi-agent system: coordinator + order agent + policy agent.

Root coordinator (:class:`ResolutionAgent`) owns the customer conversation.
It delegates read-only work to two sub-agents — the order agent (order
lookup) and the policy agent (policy knowledge base) — and it alone may call
the deterministic ``process_resolution_request`` workflow, only after the
customer confirms.

Robustness is enforced in code, not left to the model:
- the workflow validates strictly (see ``workflow.py``);
- :func:`guard_reply` checks every final reply: when a request was recorded
  the reply must say it was recorded for review, and it must never claim a
  replacement was sent, a refund was issued, or credit was applied. A reply
  that breaks either rule is replaced with a safe confirmation.
"""

from __future__ import annotations

import asyncio
import os
import re

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

from .mock_llm import ScriptedMockLlm
from .prompts import COORDINATOR_PROMPT, ORDER_AGENT_PROMPT, POLICY_AGENT_PROMPT
from .tools import (
    Store,
    get_policy,
    lookup_customer_order,
    process_resolution_request,
    set_default_store,
)

APP_NAME = "agent_resolution_workflow"
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "gemini/gemini-3.5-flash-lite")

# Phrases that must never appear in a reply: they claim money or goods moved.
# These are REGEXES, not fixed phrases: an earlier version listed ten exact
# strings, and a live model can paraphrase around any fixed list
# ("Your refund is on its way" sailed straight through). The patterns
# below match the claim shapes — refund/replacement/credit + a movement
# verb — so paraphrases are caught too. A false positive is safe here:
# the reply is replaced with a truthful "recorded for review" message.
FORBIDDEN_PATTERNS = (
    re.compile(r"replacement.{0,40}\b(sent|shipped|ship|shipping|on its way|on the way|dispatched|delivered|arriving|coming)\b"),
    re.compile(r"refund.{0,40}\b(sent|issued|on its way|on the way|processed|completed|credited|dispatched|arriving|coming)\b"),
    re.compile(r"\bcredit\b.{0,40}\b(applied|added|issued|credited)\b"),
    re.compile(r"\b(we've|we have|we)\s+(sent|shipped|issued|dispatched)\b"),
    re.compile(r"\bhas been\s+(sent|shipped|issued|refunded|dispatched|delivered)\b"),
    re.compile(r"\bhas already been\s+(sent|shipped|issued|refunded)\b"),
)

# Backwards-compatible name: the old tuple of exact phrases is gone, but
# callers that checked membership against FORBIDDEN_CLAIMS should use
# contains_forbidden_claim() instead.
FORBIDDEN_CLAIMS = tuple(p.pattern for p in FORBIDDEN_PATTERNS)


def contains_forbidden_claim(reply: str) -> bool:
    """True when a reply claims money or goods moved, in any phrasing."""
    lowered = reply.lower()
    return any(p.search(lowered) for p in FORBIDDEN_PATTERNS)

RECORDED_PHRASES = ("recorded for review", "pending review")


def guard_reply(reply: str, record_created: bool, request_id: str | None = None) -> str:
    """Check a final reply against the honesty rules; fix it if it breaks them.

    - When a request was recorded, the reply must say it was recorded for
      review. If it does not, or if it claims anything was sent, issued, or
      applied, the whole reply is replaced with a safe confirmation.
    - When nothing was recorded, a reply that claims shipment/refund is
      replaced with a safe "still pending review" sentence.
    - Anything else passes through unchanged.
    """
    lowered = reply.lower()
    bad_claim = contains_forbidden_claim(reply)
    if record_created:
        if bad_claim or not any(phrase in lowered for phrase in RECORDED_PHRASES):
            ref = f" (request {request_id})" if request_id else ""
            return (
                "Your request has been recorded for review"
                f"{ref}. A human reviews it before anything is sent or refunded."
            )
        return reply
    if bad_claim:
        return (
            "Your request is still pending review. Nothing has been sent or "
            "refunded yet — a human reviews it first."
        )
    return reply


def _live_model() -> LiteLlm:
    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY is not set; live mode unavailable")
    return LiteLlm(DEFAULT_MODEL)


def _build_llm_agent(
    name: str,
    description: str,
    instruction: str,
    model,
    tools: list,
    sub_agents: list | None = None,
) -> LlmAgent:
    return LlmAgent(
        name=name,
        description=description,
        model=model,
        instruction=instruction,
        tools=tools,
        sub_agents=sub_agents or [],
    )


class ResolutionAgent:
    """Customer resolution agent: conversation + deterministic workflow.

    Wraps a Google ADK root coordinator with two sub-agents. Mock mode
    (default) runs the loop on scripted mock LLMs: no API key, no network.
    Live mode (``live=True``) runs the same agents on Gemini via LiteLLM.

    One instance is one conversation: the ADK session keeps the dialogue
    history, so turn 2 remembers the order from turn 1. Call
    :meth:`new_conversation` to start over with the same ledger.

    Attributes:
        live: Whether live (Gemini) mode is enabled.
        store: Orders, policies, and ledger shared with the tools.
        coordinator: The root ADK agent.
        ledger_count_before: Ledger rows before the current turn, used by
            the guardrail to tell whether this turn recorded a request.
    """

    def __init__(self, live: bool = False, store: Store | None = None):
        """Build the agent. Mock by default; live needs GEMINI_API_KEY."""
        self.live = live
        self.store = store or Store.load()
        set_default_store(self.store)
        if live:
            order_model: object = _live_model()
            policy_model: object = _live_model()
            coordinator_model: object = _live_model()
        else:
            order_model = ScriptedMockLlm(role="order")
            policy_model = ScriptedMockLlm(role="policy")
            coordinator_model = ScriptedMockLlm(role="coordinator")
        order_agent = _build_llm_agent(
            name="order_agent",
            description="Looks up a Northstar Goods order by id and reports the facts.",
            instruction=ORDER_AGENT_PROMPT,
            model=order_model,
            tools=[FunctionTool(lookup_customer_order)],
        )
        policy_agent = _build_llm_agent(
            name="policy_agent",
            description="Reads the support policy knowledge base and states what it allows.",
            instruction=POLICY_AGENT_PROMPT,
            model=policy_model,
            tools=[FunctionTool(get_policy)],
        )
        self.coordinator = _build_llm_agent(
            name="resolution_coordinator",
            description="Owns the customer conversation and records resolution requests for review.",
            instruction=COORDINATOR_PROMPT,
            model=coordinator_model,
            tools=[FunctionTool(process_resolution_request)],
            sub_agents=[order_agent, policy_agent],
        )
        self._session_service = InMemorySessionService()
        self._runner = Runner(
            agent=self.coordinator,
            app_name=APP_NAME,
            session_service=self._session_service,
        )
        self._session_id: str | None = None
        self._user_id = "customer"
        self.last_request_id: str | None = None

    async def _ensure_session(self) -> str:
        if self._session_id is None:
            session = await self._session_service.create_session(
                app_name=APP_NAME, user_id=self._user_id
            )
            self._session_id = session.id
        return self._session_id

    def new_conversation(self) -> None:
        """Drop the current session; the next turn starts a fresh dialogue."""
        self._session_id = None
        self.last_request_id = None

    async def run_async(self, message: str) -> str:
        """Run one customer message through the agent loop; return the reply.

        The reply passes through :func:`guard_reply` before it is returned.
        """
        session_id = await self._ensure_session()
        before = self.store.ledger.count()
        content = types.Content(role="user", parts=[types.Part(text=message)])
        final_text = ""
        async for event in self._runner.run_async(
            user_id=self._user_id, session_id=session_id, new_message=content
        ):
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        final_text = part.text
        record_created = self.store.ledger.count() > before
        request_id = None
        if record_created:
            rows = self.store.ledger.all()
            request_id = rows[-1].request_id if rows else None
            self.last_request_id = request_id
        if not final_text.strip():
            # The loop can end with no final text (e.g. a tool-only turn):
            # never hand the customer an empty reply.
            final_text = "Sorry — I didn't get a reply for that. Could you say it again?"
        return guard_reply(final_text, record_created, request_id)

    def run(self, message: str) -> str:
        """Synchronous wrapper around :meth:`run_async`."""
        return asyncio.run(self.run_async(message))

    def ledger_rows(self) -> list[dict]:
        """Every ledger row as plain dicts (for the demo and tests)."""
        return [row.to_dict() for row in self.store.ledger.all()]

    def history(self) -> list[dict]:
        """The conversation history of the current session, if any.

        NOTE: an earlier version called ``get_session`` synchronously,
        but ADK's session service is async — the call returned an
        un-awaited coroutine and this method silently returned [] forever
        (with a RuntimeWarning). It now awaits the call properly.
        """
        if self._session_id is None:
            return []
        session = asyncio.run(self._session_service.get_session(
            app_name=APP_NAME, user_id=self._user_id, session_id=self._session_id
        ))
        if session is None:
            return []
        out: list[dict] = []
        for event in getattr(session, "events", []) or []:
            content = getattr(event, "content", None)
            if content is None:
                continue
            for part in content.parts or []:
                if part.text:
                    out.append({"role": content.role or "", "text": part.text})
        return out


def run_agent(message: str, live: bool = False, store: Store | None = None) -> str:
    """One-shot helper: build an agent, run one message, return the reply."""
    return ResolutionAgent(live=live, store=store).run(message)
