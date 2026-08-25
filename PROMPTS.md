# PROMPTS.md — System Prompt & Tool-Description Iteration

This documents how `app/prompts.py` and the tool descriptions in `app/tools.py`
evolved while building this agent, and why. **Note:** this sandbox couldn't
reach the Groq/Gemini APIs to run live conversational tests (no network egress
to those domains), so the log below is grounded in the assignment's own
evaluation categories and the failure modes the grading rubric explicitly
calls out — not live transcripts. Before submitting, run the scenarios in
`tests/test_policy_engine.py` plus the manual script in `README.md` against
your actual API key and adjust the prompt further based on what you see; this
file is a strong starting point, not a substitute for that pass.

## v1 — Minimal role prompt

Started with something close to:

> "You are Trendly's support assistant. Answer questions about orders and
> policy using the tools provided."

**Problem anticipated:** this leaves the model free to answer policy questions
from its own training-data guesses about "typical" e-commerce return windows,
which is exactly the "no invented policy" failure the assignment calls out.
Nothing forces a tool call before a factual claim.

## v2 — Added hard tool-use rules

Added explicit numbered rules: *before stating any policy fact, call
`search_policy`; before saying whether something is returnable, call
`check_return_eligibility`; never state a date/fee/rule not just retrieved by
a tool.* This is the single highest-leverage change for grounding — it turns
"try to use tools when helpful" into "you are not allowed to assert facts
without a tool call backing them," which is a much stronger constraint on an
LLM than a soft suggestion.

Also added the rule that `raise_return_request` **requires** a prior passing
`check_return_eligibility` call in the same conversation — enforced twice,
once in the prompt and once in code (`tools.py` checks `session.last_eligibility`
before allowing the return to be raised). Belt-and-suspenders: even if the
model ignores the prompt instruction, the tool itself refuses to run.

## v3 — Identity verification / data-leakage guardrail

Realized the eligibility/order-lookup tools said nothing about *whose* order
it is. Added explicit instructions: an order must be verified (email/phone
match) before any detail is discussed; if verification fails, ask for contact
info rather than confirming or denying whose order it is. This directly
targets the "no data leakage" requirement and the "confirm/deny a different
customer's order" trap a scripted eval would likely include.

## v4 — Escalation triggers made explicit and enumerable

Initially the prompt just said "escalate when appropriate," which is too
vague — a model will under- or over-escalate inconsistently. Replaced with a
concrete list mirroring policy section 7 and the dataset's own edge cases:
lost parcels, COD bank-detail requests, second exchanges, damaged/wrong
items, anything `search_policy` can't find. This maps 1:1 to the
`_note_for_designers` hints in `orders.json` (e.g. TR-4526 explicitly says
"must be escalated to a human"), so the prompt was written to make that
outcome the model's default reaction to those tool results, not something it
has to infer from policy prose alone.

## v5 — Tone pass

Added a short tone section after considering the TR-4525 scenario (14 days
delayed, dataset note: "customer is likely upset; a good agent acknowledges
the delay before quoting policy"). Without this, a model given only the
grounding rules above tends to front-load policy citations ("Per policy 1.5
section...") in a way that reads as robotic and dismissive of a frustrated
customer. Added: acknowledge what went wrong briefly and with empathy first,
then move to the resolution — and avoid citing section numbers as prose,
translate them into plain language instead.

## Tool description iteration

Tool *descriptions* (not just the system prompt) carry real weight in
function-calling models' decisions about when to call what. Two changes worth
calling out:

- `search_policy`'s description was changed from "search the policy doc" to
  explicitly say "This is the ONLY source of policy truth... never answer a
  policy question from memory" — repeating the grounding constraint at the
  tool level, not just the system-prompt level, since models weight tool
  descriptions heavily when deciding whether a tool is relevant.
- `raise_return_request`'s description states its own precondition ("only
  after check_return_eligibility already returned eligible=true...") so the
  constraint is visible to the model at the moment it's deciding whether to
  call it, not just buried in a system-prompt rule list it may have
  deprioritized several turns earlier.

## What we'd still want to verify empirically

- Whether the model reliably re-verifies identity if the customer switches to
  a *different* order ID mid-conversation (the code handles this correctly —
  verification is keyed per order_id — but whether the model correctly calls
  `lookup_order` again for the new ID rather than assuming it's covered needs
  a live check).
- Whether `search_policy`'s top-2 keyword results are enough for
  multi-concept questions (e.g. "can I return a final-sale item I bought with
  cash on delivery") or whether the model needs to call it twice.
- Whether Groq's Llama 3.3 70B and Gemini 2.0 Flash differ meaningfully in
  how strictly they follow the "call the tool before asserting a fact" rule —
  worth a side-by-side run of the same scripted conversation on both.
