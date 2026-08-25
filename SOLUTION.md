# Solution Note — Trendly Agentic Support Assistant

## Architecture

The agent is a FastAPI service with a thin chat UI. Every customer message goes
through an LLM (Groq's Llama 3.3 70B, or Gemini 2.0 Flash — switchable via
`LLM_PROVIDER`) that has six tools available and no memory of order/policy facts
beyond what those tools return in the current conversation.

```
Customer message
      │
      ▼
 LLM + tool schemas ──(tool_calls)──► Tool dispatcher ──► deterministic Python:
      │                                                     - data_store.py  (orders.json,
      │◄──────────────── tool results ──────────────────────  trendly_policy.md)
      ▼                                                     - policy_engine.py (eligibility,
 Natural-language reply                                       delay-credit rules)
```

**Split of responsibility is deliberate.** The LLM's job is orchestration and
language: deciding *which* tool to call and *when*, and phrasing the result
naturally. It never decides eligibility, dates, or fees itself — those are
computed in plain Python (`policy_engine.py`) directly from `orders.json` +
the rules in `trendly_policy.md`, and handed to the model as facts. This is
the main defense against hallucination: a wrong LLM decision about "is this
returnable" isn't possible if the LLM isn't the one deciding it.

**Six tools**, one per required capability:
- `lookup_order` — status + identity verification (gates everything else)
- `search_policy` — keyword search over the policy doc, split into its 7
  numbered sections; returns the matching section(s) verbatim so answers are
  traceable to a specific clause, not paraphrased from model memory
- `check_return_eligibility` — runs the policy engine against a specific
  order + SKU
- `raise_return_request` — refuses to run unless `check_return_eligibility`
  already passed for that exact order/SKU *in this conversation* (stops the
  model from approving something it never actually checked)
- `request_delay_credit` — same pattern for the ₹250 delay credit
- `escalate_to_human` — produces a structured ticket (reason + summary) for
  lost parcels, COD bank details, damaged items, second exchanges, and
  anything policy doesn't cover

**Multi-turn state** lives in an in-memory `Session` per `session_id`:
message history, which orders have passed identity verification, the last
eligibility result per (order, SKU) pair (the gate above), and a running list
of tickets raised. A customer can give an order ID in turn 1 and ask "can I
exchange it for a smaller size" in turn 4 without repeating themselves or
re-verifying.

**Identity verification as the data-leakage guard.** Rather than trusting
whatever order ID the customer types, `lookup_order` requires the email or
phone on file for that order the first time it's referenced in a session. The
system prompt explicitly forbids describing or confirming an order without
that match — which is also what stops one customer from fishing for details
on someone else's order.

## Key trade-offs

- **Two LLM providers, one interface.** Groq needs a hand-rolled tool-call
  loop (`groq_provider.py`); Gemini's SDK does this automatically via
  `enable_automatic_function_calling`. Built both behind `LLMProvider` so the
  rest of the app is provider-agnostic — useful for a "your call" free-tier
  requirement where API availability/rate limits can shift day to day.
- **No RAG/embeddings for the policy doc.** It's ~2 pages; a keyword-overlap
  scorer over its 7 sections is fully deterministic, auditable, and avoids
  embedding-model dependencies for a document this small. Wouldn't scale past
  maybe a few dozen pages.
- **In-memory sessions, not a database.** Fine for a demo/screening
  assignment; resets on every server restart. A real deployment needs
  persistent session + ticket storage.
- **Eligibility logic hard-coded in Python, not configurable.** Fast and
  reliable for 10 fixed orders and a fixed policy doc; if Trendly's real
  policy changes, this needs a code change, not just a doc edit. A
  rules-engine or structured-policy-as-data approach would trade simplicity
  now for easier policy updates later.
- **The 10 orders in `orders.json` only make sense against one reference
  "today."** Several of the dataset's own `_note_for_designers` hints (e.g.
  TR-4525 annotated "14 days past expected delivery" against a 2026-07-15
  expected date) only hold simultaneously on **2026-07-29** — so that's the
  default simulated "today" (`app/config.py`, overridable via
  `SIMULATED_TODAY`). Using the real current date instead would silently
  break several of the intended test scenarios (e.g. the TR-4522 tee would
  read as expired instead of returnable).

## Known limitations

- Identity verification is a simple contact-string match, not real auth —
  fine for a support-chat demo, not production-grade.
- `search_policy`'s keyword scorer can miss paraphrased questions that don't
  share vocabulary with the doc (e.g. "can I get my money back" vs "refund").
- No conversation persistence across server restarts; no multi-agent-handoff
  simulation beyond producing an escalation ticket.
- Partial-order and multi-item returns are handled per-SKU, not as a batch
  return-the-whole-order flow.
- Business-day math uses a plain Mon–Fri model; no Indian public holiday
  calendar, which the real policy references implicitly (1.1).

## Five discovery questions for Trendly's ops team

1. What does "verified identity" actually need to look like in production —
   OTP, account login, order-confirmation-email link — versus the
   email/phone match this assignment uses as a stand-in?
2. What's the real distribution of contact volume across order-status,
   returns, and "other" — is 70% repetitive really order/returns/policy, or
   does that hide a long tail (sizing advice, styling questions, complaints)
   this agent shouldn't attempt?
3. Who owns updates to `trendly_policy.md` in practice, and how often does it
   change? That determines whether hard-coded eligibility logic is
   acceptable or whether policy needs to be data-driven from day one.
4. What SLA does the human queue actually have, and should the agent's
   escalation message differ (urgency, channel) for lost parcels vs. a
   second-exchange approval vs. a damaged-item claim?
5. Is there an existing OMS/WMS API this should call instead of a static
   JSON file, and what does its error/rate-limit behavior look like — the
   agent's failure-recovery story is very different for "static lookup" vs.
   "flaky upstream API."
