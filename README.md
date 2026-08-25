# Trendly Agentic Support Assistant

An agent for Trendly's support chat: order status, shipping/returns policy
questions, and return/exchange eligibility, with real tool-calling and clean
escalation to a human when it should hand off. Built for the Yellow.ai FDE
Intern screening assignment.

- **Stack:** Python, FastAPI, plain HTML/JS chat UI
- **LLM:** Groq (Llama 3.3 70B) or Gemini (2.0 Flash) — switchable, both on
  free tiers
- **Data:** `data/orders.json` and `data/trendly_policy.md`, loaded as-is

See `SOLUTION.md` for architecture/trade-offs/limitations and `PROMPTS.md`
for how the system prompt was iterated.

gkggggggggggggggggggggg
---
---

## 🎥 Demo Video

<a href="https://www.youtube.com/watch?v=AK-ZdJsgP9k">
  <img src="https://img.youtube.com/vi/AK-ZdJsgP9k/maxresdefault.jpg" alt="FailFix AI Demo" width="1000">
</a>

### ▶️ Watch the FailFix AI Demo

Click the video preview above to watch the complete FailFix AI demonstration on YouTube.

---

## Quick start

```bash
git clone <this-repo>
cd trendly-support-agent
cp .env.example .env
# edit .env: set LLM_PROVIDER=groq or gemini, and the matching API key
pip install -r requirements.txt --break-system-packages   # or use a venv
uvicorn app.main:app --reload --port 8000
```

Or just run `./scripts/run_local.sh`, which creates a virtualenv, installs
dependencies, copies `.env.example` → `.env` on first run, and starts the
server.

Then open **http://localhost:8000** for the chat UI, or talk to it directly:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Whats your return window?"}'
```

Get free API keys here:
- Groq: https://console.groq.com/keys
- Gemini: https://aistudio.google.com/apikey

## Running the offline tests

The eligibility/delay-credit logic is plain Python with no LLM dependency, so
it can be verified with zero API keys:

```bash
pip install pytest --break-system-packages
pytest tests/ -v
```

This checks all 10 fixed orders in `orders.json` against the policy rules —
happy path, non-returnable categories, expired window, final sale, cancelled
order, lost parcel, and the delay-credit trigger.

## Trying it manually

A few conversations worth running by hand (also good material for the demo
video):

- **Order status + edge case:** "what's going on with order TR-4525" → should
  acknowledge the delay, then offer to check delay credit eligibility.
- **Policy grounding:** "what's your return window" → should call
  `search_policy` and answer from policy section 2.1, not from memory.
- **Eligibility + refusal:** "can I return order TR-4527, the earrings" (after
  verifying with `priya.nair@example.com`) → should refuse on category
  grounds (jewellery), not date grounds, even though it's well within 30 days.
- **Escalation:** "my order TR-4526 never showed up" → should recognize the
  `lost_in_transit` status and escalate rather than trying to process a return.
- **Data leakage / verification:** ask about an order without providing the
  right email/phone → should ask for verification, not describe the order.
- **Refusal:** "can you give me a discount for the trouble" → should decline;
  no discount exists in policy outside what's explicitly defined.

## Switching LLM provider

Set `LLM_PROVIDER=groq` or `LLM_PROVIDER=gemini` in `.env`. Both implement the
same `LLMProvider` interface (`app/llm/base.py`), so nothing else in the app
needs to change. See `SOLUTION.md` for how the two tool-calling loops differ
(Groq's is hand-rolled; Gemini's uses the SDK's automatic function calling).

## Deploying (free tier)

Any host that runs a `Procfile`/one uvicorn command works — Render, Railway,
Fly.io, etc. Included `Procfile`:

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Steps for Render (free web service):
1. Push this repo to GitHub.
2. New → Web Service → connect the repo.
3. Build command: `pip install -r requirements.txt`
   Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add `LLM_PROVIDER`, `GROQ_API_KEY`/`GEMINI_API_KEY` etc. as environment
   variables in the dashboard (don't commit `.env`).
5. Deploy — the live URL is your submission's "live endpoint."

## Project structure

```
app/
  config.py          # env vars, and the calibrated "today" for the fixed dataset
  data_store.py       # loads orders.json + trendly_policy.md, policy search
  policy_engine.py     # deterministic eligibility / delay-credit rules
  sessions.py          # in-memory multi-turn state per session_id
  tools.py             # the 6 tools + their schemas
  prompts.py           # system prompt
  main.py              # FastAPI app
  llm/
    base.py            # provider interface
    groq_provider.py    # manual tool-call loop (OpenAI-compatible API)
    gemini_provider.py  # automatic function calling
data/
  orders.json          # provided, loaded as-is
  trendly_policy.md    # provided, loaded as-is
static/index.html      # chat UI
tests/test_policy_engine.py  # offline tests, no API key needed
SOLUTION.md             # architecture, trade-offs, limitations, discovery questions
PROMPTS.md              # prompt iteration log
```

## A note on the reference date

`orders.json` is a fixed dataset — its own `_note_for_designers` fields only
make sense read against one specific "today" (worked out from TR-4525's "14
days past expected delivery" note against its `expected_delivery` of
2026-07-15, cross-checked against all 9 other orders — see `SOLUTION.md`).
That date, **2026-07-29**, is the default in `app/config.py`. Override with
`SIMULATED_TODAY` in `.env` if you want to test other dates, or unset it to
use the real current date.

## AI-usage note

This project (backend architecture, tool design, policy-engine logic, prompt
drafting, frontend, and docs) was built with  help end-to-end,
including catching and fixing a real bug during development (an unset
reference-date assumption that would have silently broken several of the
dataset's intended test scenarios — see `SOLUTION.md`). Replace this note
with your own honest account of what you generated vs. wrote/modified
yourself, per the assignment's instructions — be ready to explain and modify
any part of this code live if shortlisted.

---

##  Author

**Niveditha **

Data Science & Machine Learning  | AI/ML Developer

- LinkedIn: [Niveditha.](https://www.linkedin.com/in/niveditha-89ba04356/)

---
