"""Deterministic scripted mock LLMs for the ADK agent loop (no key, no network).

One mock class, one ``role`` per agent: the coordinator mock drives the
conversation state machine, the order mock drives the read-only lookup, and
the policy mock drives the policy lookup. Each mock reads only the request
contents — what the user said, what tools already returned, and what the
sub-agents already reported — so the whole multi-agent loop is testable
offline with the same code path the live run uses.

Sub-agents report back by transferring to the coordinator: the order and
policy facts travel in the quoted tool-result transcripts ADK appends to the
parent's history, and the coordinator mock parses those transcripts. The
live Gemini agents do not need any of this; they read natural language.
"""

from __future__ import annotations

import re
from typing import AsyncGenerator

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types

from .policies import find_policy_for
from .workflow import normalize_resolution

ORDER_RE = re.compile(r"CM-\d+", re.IGNORECASE)
CONFIRM_WORDS = (
    "yes, please",
    "yes please",
    "please go ahead",
    "go ahead",
    "please do",
    "sounds good",
    "that's right",
    "that's correct",
    "yes, go ahead",
)

# Words that negate a confirmation. Checked BEFORE the confirm words:
# "don't go ahead" contains "go ahead" as a substring, and "I need to
# confirm my address" contains "confirm" — neither is a confirmation.
NEGATION_WORDS = (
    "don't", "do not", "dont", "not yet", "no,", "never", "stop",
    "cancel", "not now", "hold on",
)


def _is_confirmation(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered.rstrip(".") in ("yes", "yeah", "yep", "confirm", "confirmed",
                               "ok", "okay", "sure", "please do"):
        return True
    if any(neg in lowered for neg in NEGATION_WORDS):
        return False
    return any(word in lowered for word in CONFIRM_WORDS)


def _text_parts(request: LlmRequest) -> list[tuple[str, str]]:
    """Every text part in the request, in order: (role, text)."""
    out: list[tuple[str, str]] = []
    for content in request.contents or []:
        for part in content.parts or []:
            if part.text:
                out.append((content.role or "", part.text))
            if part.function_response is not None:
                out.append(("function_response", str(part.function_response.response or "")))
    return out


def _is_real_user_text(text: str | None) -> bool:
    """True for a genuine customer message, not an ADK transfer transcript."""
    return bool(
        text
        and "BEGIN_QUOTED_AGENT_CONTENT" not in text
        and not text.startswith("For context:")
    )


def _last_user_text(request: LlmRequest) -> str:
    for content in reversed(request.contents or []):
        if content.role == "user":
            for part in content.parts or []:
                if _is_real_user_text(part.text):
                    return part.text
    return ""


def _user_texts(request: LlmRequest) -> list[str]:
    texts: list[str] = []
    for content in request.contents or []:
        if content.role == "user":
            for part in content.parts or []:
                if _is_real_user_text(part.text):
                    texts.append(part.text)
    return texts


def _fresh_function_response(request: LlmRequest) -> tuple[str, dict] | None:
    """The most recent function response AFTER the last real customer message.

    The request carries the whole session history, so a response from a
    previous turn must not be mistaken for a fresh one: only a response
    that comes after the latest genuine user message counts.
    """
    contents = request.contents or []
    last_user_idx = -1
    for i, content in enumerate(contents):
        if content.role != "user":
            continue
        for part in content.parts or []:
            if _is_real_user_text(part.text):
                last_user_idx = i
                break
    for content in reversed(contents[last_user_idx + 1 :]):
        for part in content.parts or []:
            if part.function_response is not None:
                return part.function_response.name, dict(part.function_response.response or {})
    return None


def _final(text: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=text)]),
        turn_complete=True,
    )


def _call(name: str, args: dict) -> LlmResponse:
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
        ),
        turn_complete=True,
    )


def _last_mentioned(texts: list[str], extract) -> str | None:
    """Last non-None value of ``extract`` over the texts, newest first."""
    for text in reversed(texts):
        value = extract(text)
        if value:
            return value
    return None


def _order_id(text: str) -> str | None:
    match = ORDER_RE.search(text)
    return match.group(0).upper() if match else None


def _category(text: str) -> str | None:
    policy = find_policy_for(text)
    return policy.category if policy else None


class ScriptedMockLlm(BaseLlm):
    """A BaseLlm that deterministically plays one agent role."""

    model: str = "mock-resolution-llm"
    role: str = "coordinator"

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"mock-.*"]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if self.role == "order":
            yield self._order_turn(llm_request)
        elif self.role == "policy":
            yield self._policy_turn(llm_request)
        else:
            yield self._coordinator_turn(llm_request)

    # -- order agent -----------------------------------------------------
    def _order_turn(self, request: LlmRequest) -> LlmResponse:
        result = _fresh_function_response(request)
        if result is not None and result[0] == "lookup_customer_order":
            # Work done: hand control back to the coordinator. The order
            # facts travel in the quoted tool-result transcript ADK appends
            # to the parent's history, so no final text is needed here.
            return _call("transfer_to_agent", {"agent_name": "resolution_coordinator"})
        order_id = _order_id(_last_user_text(request))
        if order_id:
            return _call("lookup_customer_order", {"order_id": order_id})
        return _call("transfer_to_agent", {"agent_name": "resolution_coordinator"})

    # -- policy agent ----------------------------------------------------
    def _policy_turn(self, request: LlmRequest) -> LlmResponse:
        result = _fresh_function_response(request)
        if result is not None and result[0] == "get_policy":
            # Work done: hand control back to the coordinator. The policy
            # facts travel in the quoted tool-result transcript.
            return _call("transfer_to_agent", {"agent_name": "resolution_coordinator"})
        category = _category(_last_user_text(request))
        if category:
            return _call("get_policy", {"issue_category": category})
        return _call("transfer_to_agent", {"agent_name": "resolution_coordinator"})

    # -- coordinator -----------------------------------------------------
    def _coordinator_turn(self, request: LlmRequest) -> LlmResponse:
        result = _fresh_function_response(request)
        if result is not None and result[0] == "process_resolution_request":
            return _final(self._workflow_reply(result[1]))
        if result is not None and result[0] == "transfer_to_agent":
            # The sub-agent just reported back; fall through to the state
            # machine below, which reads the transcripts from the history.
            pass

        texts = _all_text(request)
        user_texts = _user_texts(request)
        latest_user = user_texts[-1] if user_texts else ""

        order_id = _last_mentioned(user_texts, _order_id)
        category = _last_mentioned(user_texts, _category)
        resolution = _last_mentioned(user_texts, normalize_resolution)
        confirmed = _is_confirmation(latest_user)

        # Evidence from the sub-agents, scoped to the CURRENT order/category:
        # a lookup for a different order does not count.
        order_facts = _tool_result(texts, "lookup_customer_order")
        policy_facts = _tool_result(texts, "get_policy")
        order_known = (
            order_facts is not None
            and order_facts.get("found") is True
            and str(order_facts.get("order_id", "")).upper() == (order_id or "")
        )
        lookup_failed = (
            order_facts is not None
            and order_facts.get("found") is False
            and str(order_facts.get("order_id", "")).upper() == (order_id or "")
        )
        policy_known = (
            policy_facts is not None
            and policy_facts.get("found") is True
            and str(policy_facts.get("category", "")) == (category or "")
        )
        policy_failed = (
            policy_facts is not None
            and policy_facts.get("found") is False
            and str(policy_facts.get("issue_category", "")) == (category or "")
        )

        if order_id is None:
            return _final(
                "I'm sorry to hear that. Could you share your order number "
                "so I can look it up?"
            )
        if lookup_failed:
            return _final(
                f"I couldn't find order {order_id} in our records. Could you "
                "double-check the order number?"
            )
        if not order_known:
            return _call("transfer_to_agent", {"agent_name": "order_agent"})
        if policy_failed:
            return _final(
                "I don't have a support policy that covers that situation, "
                "so I can't record a request for it. Could you tell me a "
                "bit more about what happened?"
            )
        if not policy_known:
            return _call("transfer_to_agent", {"agent_name": "policy_agent"})
        if resolution is None:
            allowed = ", ".join(policy_facts.get("allowed_resolutions") or [])
            return _final(
                f"Thanks — I've checked your order and the {category} policy. "
                f"Under that policy you can choose {allowed}. "
                "Which would you like?"
            )
        allowed_resolutions = [str(r) for r in (policy_facts.get("allowed_resolutions") or [])]
        if resolution not in allowed_resolutions:
            allowed = ", ".join(allowed_resolutions)
            return _final(
                f"The {category} policy doesn't allow a {resolution}. Under "
                f"that policy you can choose {allowed}. Which would you like?"
            )
        if not confirmed:
            return _final(
                f"A {resolution} is supported for this. Shall I record a "
                f"{resolution} request for order {order_id} for review? "
                "Please confirm and I'll record it."
            )
        email = str(order_facts.get("customer_email") or "") if order_facts else ""
        note = user_texts[0] if user_texts else ""
        return _call(
            "process_resolution_request",
            {
                "order_id": order_id,
                "customer_email": email,
                "issue_category": category or "",
                "requested_resolution": resolution,
                "customer_confirmed": True,
                "agent_note": f"Customer reported: {note}",
            },
        )

    def _workflow_reply(self, result: dict) -> str:
        if result.get("ok"):
            record = result.get("record") or {}
            return (
                f"Thanks for confirming. Your {record.get('requested_resolution')} "
                f"request for order {record.get('order_id')} has been recorded "
                f"for review — request {result.get('request_id')}. A human "
                "reviews it before anything is sent or refunded."
            )
        reason = result.get("reason", "")
        message = result.get("message", "That request could not be recorded.")
        if reason == "duplicate_pending":
            return (
                f"I couldn't record a second request — {message} "
                "Your original request is still pending review."
            )
        return f"I couldn't record that request — {message}"


def _all_text(request: LlmRequest) -> str:
    return "\n".join(text for _, text in _text_parts(request))


def _tool_result(all_text: str, tool_name: str) -> dict | None:
    """Parse the quoted result transcript of a sub-agent's tool call.

    ADK appends transcripts like::

        [order_agent] `lookup_customer_order` tool returned result:
        <<<BEGIN_QUOTED_AGENT_CONTENT>>>
        {'found': True, 'order_id': 'CM-1042', ...}
        <<<END_QUOTED_AGENT_CONTENT>>>

    Returns the dict (via a safe literal parse) or None when the tool has
    not returned yet.
    """
    import ast

    marker = f"`{tool_name}` tool returned result:"
    idx = all_text.rfind(marker)
    if idx == -1:
        return None
    start = all_text.find("<<<BEGIN_QUOTED_AGENT_CONTENT>>>", idx)
    end = all_text.find("<<<END_QUOTED_AGENT_CONTENT>>>", start)
    if start == -1 or end == -1:
        return None
    payload = all_text[start + len("<<<BEGIN_QUOTED_AGENT_CONTENT>>>") : end].strip()
    try:
        parsed = ast.literal_eval(payload)
    except (ValueError, SyntaxError):
        return None
    return parsed if isinstance(parsed, dict) else None
