# agent-resolution-workflow

Customer resolution agent in the spirit of the n8n demo: a conversational
agent checks policies and orders, then calls a deterministic **Process
Resolution Request** workflow that validates the resolution and writes a
`pending_review` record — it never issues refunds or ships replacements.

This project builds the conversational-resolution pattern in code — a
conversational front end over a deterministic workflow, built with Google
ADK in Python for the fictional store Northstar Goods.

## The problem

Support conversations are open-ended: a customer can say anything, in any
order, and leave half the details out. But the step that records a
resolution — the one a refund or a replacement hangs off — must be
predictable. An agent that free-forms its way into issuing refunds is a
liability: it can record a resolution the policy does not allow, record the
same request twice, or tell a customer a replacement is already on its way
when nothing has happened.

## The split

| Half | Who does it | What it may do |
| --- | --- | --- |
| Conversation | ADK multi-agent system (below) | Ask, look up, check policy, confirm |
| Resolution | Deterministic `process_resolution_request` workflow (plain code) | Validate strictly, write one `pending_review` row |

The agent decides *whether* to ask, search a policy, look up an order, or
record a request. The workflow decides *whether the request is valid* — and
it is the only thing that writes.

```
customer message
  → resolution_coordinator (owns the conversation)
      → order_agent ──→ lookup_customer_order (read-only)
      → policy_agent ──→ get_policy (read-only, Markdown KB)
  → customer confirms the resolution they want
  → process_resolution_request (deterministic workflow)
      → validates: known order · matching email · confirmed ·
        policy allows it · condition met · inside window · no duplicate
      → writes ONE pending_review row to the SQLite ledger
  → agent replies: "recorded for review" (never "sent" or "refunded")
```

## The agents (Google ADK)

Why ADK: this pattern is exactly what ADK's agent tree is for — a root
coordinator that delegates read-only work to sub-agents and owns the one
write. Three agents, three jobs, each with its own instructions in
[`prompts.py`](src/agent_resolution_workflow/prompts.py):

- **resolution_coordinator** — owns the customer conversation, routes work
  to the sub-agents, confirms the resolution with the customer, and is the
  only agent that may call the workflow tool.
- **order_agent** — read-only order lookup. Reports facts, decides nothing.
- **policy_agent** — reads the policy knowledge base and states what it
  allows. Decides nothing, records nothing.

One ADK subtlety worth knowing: when a sub-agent answers with a final
reply, that reply ends the turn — the coordinator never gets to continue.
So the sub-agents are instructed to **transfer back to the coordinator**
after their tool call, with the facts travelling in the transfer
transcript. The coordinator then carries on. (The scripted mock LLMs in
`mock_llm.py` model exactly this hand-back, so the offline tests exercise
the same flow the live run uses.)

The LLM is LiteLLM, model from `LLM_MODEL`, default
`gemini/gemini-3.5-flash-lite` — swap models by changing one env var.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# One-command demo: CM-1042 arrived damaged → replacement → confirm → recorded
python -m agent_resolution_workflow demo

# Free-form chat with the agent
python -m agent_resolution_workflow chat

# Live (real Gemini instead of the scripted mock)
python -m agent_resolution_workflow demo --live   # needs GEMINI_API_KEY
```

Demo transcript (mock mode):

```
CUSTOMER: Hi, my order CM-1042 arrived damaged.
AGENT: Thanks — I've checked your order and the damaged_defective policy.
  Under that policy you can choose replacement, refund. Which would you like?
CUSTOMER: I would like a replacement.
AGENT: A replacement is supported for this. Shall I record a replacement
  request for order CM-1042 for review? Please confirm and I'll record it.
CUSTOMER: Yes, please go ahead.
AGENT: Thanks for confirming. Your replacement request for order CM-1042
  has been recorded for review — request RR-0002. A human reviews it before
  anything is sent or refunded.

LEDGER: RR-0001 | CM-1048 | store_credit | pending_review | late_delivery
        RR-0002 | CM-1042 | replacement  | pending_review | damaged_defective
```

## Data and policies

- [`data/customer_orders.csv`](data/customer_orders.csv) — 10 Northstar
  Goods orders, including the demo case CM-1042 (Ceramic Pour-Over Coffee
  Set, delivered 2026-11-10) and edge cases: a late delivery (CM-1043,
  8 days late), a wrong item (CM-1044), an order past the 30-day window
  (CM-1045), one still in transit (CM-1047), and a cancelled order (CM-1049).
- [`knowledge_base/`](knowledge_base/) — four policy Markdown files
  (damaged/defective, late delivery, wrong item, general returns). Each
  file carries machine-readable headers (`Category:`, `Allowed
  resolutions:`, `Window:`) plus the prose the agent reads — the workflow
  validates against the same headers, so the policy the agent quotes and
  the policy the workflow enforces can never drift apart.
- [`data/resolution_requests.csv`](data/resolution_requests.csv) — the
  seed for the SQLite ledger: one prior pending row (RR-0001, CM-1048,
  store_credit). The ledger itself lives in
  `data/resolution_requests.db` (created on first run, gitignored).

## The workflow's rules

`process_resolution_request` rejects, in order, with a typed reason:

| Reason | When |
| --- | --- |
| `unknown_order` | No such order |
| `email_mismatch` | Email does not match the order |
| `confirmation_required` | Customer has not confirmed |
| `unknown_policy` | No policy covers the issue |
| `order_not_eligible` | Order cancelled or not yet delivered |
| `resolution_not_allowed` | Policy does not allow that resolution (e.g. full refund for a late delivery — only shipping refund / store credit) |
| `condition_not_met` | Policy condition fails (e.g. delivery was not at least 5 days late) |
| `outside_window` | Past the 30-day window |
| `duplicate_pending` | Same order already has a pending request for the same resolution |

On top of that, `guard_reply` checks every final reply: when a request was
recorded the reply must say it was recorded for review, and it must never
claim a replacement was sent, a refund was issued, or credit was applied.
The check is pattern-based, not a fixed phrase list — a live model can
paraphrase around any fixed list ("your refund is on its way" used to slip
through), so the patterns match the claim shapes (refund/replacement/credit
+ a movement verb). A reply that breaks either rule is replaced with a
safe confirmation.

## Tests

```bash
pytest -q   # 65 offline tests, deterministic scripted mock LLMs, no key needed
```

Coverage: order lookup, policy retrieval (right policy for damaged vs
late vs wrong-item vs return), every workflow rejection, the full scripted
demo flow, session memory across turns, the duplicate case in conversation,
the unsupported-resolution case in conversation, the reply guardrail, and
the ADK tool functions.

Live test (`scripts/live_test.py`, run via the Gemini harness):

```
python3 ~/workspace/custom-connectors/custom.gemini/bin/run_live.py \
    ~/workspace/agent-resolution-workflow .venv/bin/python scripts/live_test.py
```

**Live test PASSED** (Tue 2026-11-24, 22.3 s, real Gemini
`gemini-3.5-flash-lite`, report `.runs/live/attempt-1/report.json`):
turn 1 named both allowed resolutions; turn 2 asked for confirmation and
recorded nothing; turn 3 recorded exactly one `pending_review` row
(RR-0002, CM-1042, replacement, damaged_defective) and the reply said
"recorded for review" with the request id; the duplicate request was
rejected with no new row; a full refund for late-delivery order CM-1043
was rejected with `resolution_not_allowed`.

Two things the live run taught us, both now in the code: (1) sub-agents
must transfer back to the coordinator instead of answering the customer —
the first live attempt returned the raw order dump as the reply; (2) the
live coordinator spots a duplicate from the conversation history and
explains it without needing a confirmation round-trip.

Re-verified after an independent code review on Tue 2026-11-24 (29.6 s,
same checks, report `.runs/live/attempt-3/report.json`): the review fixed
the reply guardrail (pattern-based, not a fixed phrase list), the
`history()` session lookup, the workflow's reference date (now the real
current date, demo pins STORE_TODAY), malformed-date handling, and a
DB-level duplicate guarantee. One review note from that run: the model
once cited the request id as "RR-1042" alongside the real RR-0002 — the
workflow returns the correct id; the prose garbling is model noise.

## How this differs from agent-support-resolution

Bala's earlier repo is LangGraph + policy-as-code with a $50 refund cap and
a human-review hold. This one is a different pattern: Google ADK
multi-agent (coordinator + order/policy sub-agents), a Markdown policy
knowledge base the agent retrieves from, session memory across turns, and
the explicit agent-vs-workflow split where the deterministic workflow is
the only writer.

## Honest limits

- Nothing here issues a refund, ships a replacement, or changes an order.
  The workflow writes a `pending_review` row; a human reviews it. That is
  the point — and the limit.
- The workflow is a Python function in this repo, not an n8n workflow.
  The pattern is the same; the runtime is not.
- The demo pins the store's reference date at 2026-11-24 (`STORE_TODAY` in
  `workflow.py`, set on the demo store) so the shipped order dates and the
  30-day window checks are deterministic whenever the demo runs. The
  workflow itself defaults to the real current date — an earlier version
  defaulted to the frozen date, which made the window check meaningless in
  real use.
- The demo ledger is a throwaway SQLite file so the demo is repeatable, and
  it is deleted when the demo ends; `chat` mode uses the persistent
  `data/resolution_requests.db`.
- Session memory is ADK's in-memory session service: it lasts for the
  process, not across restarts.
