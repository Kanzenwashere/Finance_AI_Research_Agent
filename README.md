# Finance AI Research Agent

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

## Install

```bash
git clone https://github.com/Kanzensucks/Finance_AI_Research_Agent.git
cd Finance_AI_Research_Agent
pip install -e .
cp .env.example .env        # then add your ANTHROPIC_API_KEY
```

## Use it from the command line

```bash
finance-research AAPL
finance-research --model claude-opus-4-8 NVDA
finance-research --json TSLA > meeting.json
```

The desk streams in as each analyst lands, then the bear makes its case, then a
"no rating — your call" line. Nothing tells you what to do.

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
| **Valuation** | cheap or expensive, and what's priced in |
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
