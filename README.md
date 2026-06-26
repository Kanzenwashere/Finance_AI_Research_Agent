# Finance AI Research Agent

**Live demo:** https://web-production-52074.up.railway.app/

**A multi-agent investment research desk that argues a stock from every side — and refuses to give you a rating.**

Point it at a ticker. A panel of analyst agents — **Bull, Valuation, Macro, and a quality
Checklist** — each research it in parallel, blind to one another. Then a **Bear analyst** is
handed the bull and valuation cases and told to tear them apart. You get the strongest case
each way and the risks that matter — **never a buy/sell rating**. The judgment stays with you.

```
                ┌──────────────┐
   ticker       │  Bull        │──┐
   (AAPL)  ──▶  ├──────────────┤  │
                │  Valuation   │──┤   research in parallel,
                ├──────────────┤  │   each blind to the others
                │  Macro       │──┤
                ├──────────────┤  │
                │  Checklist   │──┘
                └──────────────┘
                       │
                       ▼
                ┌──────────────────────────────┐
                │  BEAR / RED TEAM              │
                │  fed the bull + valuation,    │
                │  told to attack them          │
                └──────────────────────────────┘
                       │
                       ▼
            strongest case each way  →  YOU DECIDE
            (no rating, no price target, no "answer")
```

---

## Why

Most "AI stock" tools rush to a confident call — *buy, $250 target, strong conviction*. That's
exactly when a language model is most dangerous: fluent, decisive, and sometimes confidently
wrong in ways you can't see.

This does the opposite on purpose. It forces *opposing*, well-argued cases into the open,
red-teams the optimism, and leaves the decision — and the accountability — with the human. The
tension is the product, not a number.

---

## Run it yourself

```bash
git clone https://github.com/Kanzensucks/Finance_AI_Research_Agent.git
cd Finance_AI_Research_Agent
pip install -e ".[web]"      # core agent + the web demo (FastAPI + uvicorn)
cp .env.example .env         # then add your ANTHROPIC_API_KEY
```

**From the command line:**

```bash
finance-research AAPL
finance-research --model claude-opus-4-8 NVDA
finance-research --json TSLA > meeting.json
```

The desk streams in as each analyst lands, then the bear makes its case, then a
"no rating — your call" line. Nothing tells you what to do.

**As a local web app** — a small tabbed workspace around the same engine, streamed live over
Server-Sent Events:

```bash
uvicorn research_firm.web:app --reload      # then open http://localhost:8000
```

- **Research** — search by ticker *or* company name (autocomplete), run the desk, and read each
  analyst as a compact card you expand into its full memo. The Valuation card leads with a real
  **discounted-cash-flow model** — an intrinsic-value range, the assumptions, and a sensitivity
  grid. Then the Bear, then a "no verdict" banner. Send a name to your Watchlist or Radar in a tap.
- **Watchlist / Radar** — two saved lists (committed vs. still-weighing). Re-opening a stock you've
  already researched restores the saved memos instantly — **no tokens spent** — with a button to
  run a fresh meeting when you want one.
- **Book** — track holdings; each prices itself from the market feed (no meeting needed) and shows
  per-position value and naive cost-basis gain/loss. It reviews each holding on its own and
  deliberately **never scores, rates, or ranks the portfolio**.
- **Balance** — a plain description of your book's sector mix. No concentration score, no risk
  rating, no rebalancing advice.

Everything user-specific lives in your browser (`localStorage` only — no account, no server
storage). With **no `ANTHROPIC_API_KEY` set**, the page still works — it serves a saved example run
so you can see the UI without spending anything.

## Deploy your own

It runs anywhere that can serve a FastAPI app. The repo ships a `Procfile`, a `requirements.txt`,
and a `[web]` extra, so a one-click host like **Railway** works out of the box:

1. Point a new service at this repo.
2. Set `ANTHROPIC_API_KEY` as an environment variable (put a hard spend limit on the key — that's
   your real cost backstop).
3. Start command (also in the `Procfile`):
   `uvicorn research_firm.web:app --host 0.0.0.0 --port $PORT`.

It's a **public demo with no auth wall**, so it ships cheap guardrails: a per-IP hourly limit
(`RATE_LIMIT_PER_HOUR`, default 3) and a global daily cap (`DAILY_CAP`, default 60). Past either —
or if the key is missing or a run errors — it serves a committed **saved run** instead of failing,
so the link always returns something and never runs up a bill.

## Use it as a library

```python
from research_firm import hold_meeting

meeting = hold_meeting("AAPL")

for analyst, view in meeting.views.items():
    print(analyst, "→", view)

print("BEAR:", meeting.bear)
# meeting.verdict does not exist — by design.
```

---

## The desk

| Analyst | Job |
| --- | --- |
| **Bull** | the strongest evidence-based case *for* owning it |
| **Valuation** | runs a real DCF and gives an intrinsic-value *range* — never a single target |
| **Macro** | the sector / rates / cycle backdrop — tailwind, neutral, or headwind |
| **Checklist** | a short PASS / FLAG / FAIL due-diligence gate |
| **Bear** | runs last, fed the bull + valuation, and attacks them |

Live market context (price, multiples, business summary) is pulled from Yahoo Finance via
`yfinance` and handed to every analyst, so they reason about the real company.

---

## How it's built

- **Parallel desk.** Each analyst is one fixed mandate, run concurrently as an independent call
  that never sees another analyst's output.
- **Adversarial bear, last.** The bear is fed the bull and valuation cases specifically so its
  rebuttal attacks the actual argument, not a strawman.
- **No synthesis.** The engine never collapses the debate into a rating or target; `Meeting` has
  no `verdict` field on purpose.
- **Real valuation.** The Valuation analyst reasons over a clean-room two-stage discounted-cash-flow
  model — whole-company: project free cash flow, discount at a CAPM-based WACC, terminal value, net
  out debt — that outputs an intrinsic-value *range* (a sensitivity grid), not a single number.
- **Resilient.** One analyst failing — an API error or a malformed reply — is captured in its
  slot and never sinks the meeting; the bear still runs on whoever produced a view.
- **One call.** `hold_meeting(ticker) -> Meeting`, with a CLI on top and hermetic tests around it.

## Run the tests

```bash
pip install -e ".[dev]"
pytest
```

The tests are hermetic — the model client and the market feed are both faked, so they run with
no network and no API key.

---

## Not investment advice

This is a research and engineering project. Its output is AI-generated analysis for thinking, not
a recommendation to buy or sell anything. It deliberately gives no rating — do your own diligence.

MIT licensed. Built by [Kanzen](https://github.com/Kanzensucks).
