"""The firm meeting.

`hold_meeting(ticker)` pulls a market snapshot, runs the analyst desk concurrently (each blind
to the others), then runs the Bear last — fed the Bull and Valuation cases so its rebuttal is
against the actual argument. It returns a `Meeting`: every analyst's view plus the bear's
attack, and — by design — no verdict. The firm surfaces the dissent; the human decides.

A single analyst failing (an API error or an empty reply) is captured in its slot and never
sinks the meeting; the bear still runs on whatever the desk produced.
"""
from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass, field
from typing import Any, Callable

from anthropic import Anthropic

from research_firm import market
from research_firm.analysts import BEAR, DESK, Analyst

# Sonnet by default: a meeting fans out to several analyst calls plus the bear, so the mid-tier
# is a deliberate cost choice. Override per call with hold_meeting(model=...).
DEFAULT_MODEL = "claude-sonnet-4-6"
# The mandates target a ~700-token case but tell the analyst to reserve room for its closing line;
# this cap leaves a comfortable buffer so even the longest seat (the Bear) lands its close.
DEFAULT_MAX_TOKENS = 1100
DEFAULT_TIMEOUT = 90  # seconds per analyst call (longer replies need a touch more time)


@dataclass
class Meeting:
    """The record of one meeting. Note: there is intentionally no `verdict` / `rating` field —
    the strongest case each way is the output, and the call is the reader's."""
    ticker: str
    profile: dict[str, Any] = field(default_factory=dict)
    views: dict[str, str] = field(default_factory=dict)    # analyst name -> argument
    errors: dict[str, str] = field(default_factory=dict)   # analyst name -> failure reason
    bear: str | None = None
    bear_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "profile": self.profile,
            "views": self.views,
            "errors": self.errors,
            "bear": self.bear,
            "bear_error": self.bear_error,
        }


def _complete(client: Anthropic, system: str, user: str, *,
              model: str, max_tokens: int, timeout: int) -> str:
    """One analyst turn. Raises on an API error or an empty / non-text reply — both are caught
    by the caller and recorded as a failed slot, so a malformed response can't sink the run."""
    msg = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}], timeout=timeout,
    )
    text = next((b.text for b in (msg.content or []) if getattr(b, "text", None)), None)
    if not text:
        raise ValueError("the model returned no text content")
    return text.strip()


def hold_meeting(
    ticker: str,
    *,
    client: Anthropic | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
    fetch: Callable[[str], dict[str, Any]] = market.snapshot,
    on_event: Callable[[str], None] | None = None,
    on_analyst: Callable[[str, str | None, str | None], None] | None = None,
) -> Meeting:
    """Run a full research meeting on `ticker` and return the structured dissent (no verdict).

    `fetch` is the market-data source (injectable for tests). `on_event(tag)` is an optional
    progress hook ("view:Bull", "error:Macro", "bear"). `on_analyst(name, view, error)` is an
    optional content hook that fires as each analyst — and the Bear (name "Bear") — lands, with the
    actual argument text, so a caller can stream the debate live. Neither hook is ever allowed to
    be fatal.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("A ticker is required.")
    client = client or Anthropic()
    meeting = Meeting(ticker=ticker, profile=fetch(ticker))

    def emit(tag: str) -> None:
        if on_event:
            try:
                on_event(tag)
            except Exception:  # noqa: BLE001 — a progress hook must never break the run
                pass

    def emit_analyst(name: str, view: str | None, err: str | None) -> None:
        if on_analyst:
            try:
                on_analyst(name, view, err)
            except Exception:  # noqa: BLE001 — a content hook must never break the run
                pass

    context = market.format_context(ticker, meeting.profile)

    def run_analyst(a: Analyst, extra: str = "") -> tuple[str, str | None, str | None]:
        try:
            view = _complete(client, a.mandate, f"{context}\n\n{extra}".strip(),
                             model=model, max_tokens=max_tokens, timeout=timeout)
            return a.name, view, None
        except Exception as err:  # noqa: BLE001 — per-analyst isolation: one failure never sinks the meeting
            return a.name, None, f"{type(err).__name__}: {err}"

    # The desk argues in parallel — each analyst blind to the others.
    with cf.ThreadPoolExecutor(max_workers=len(DESK)) as pool:
        futures = [pool.submit(run_analyst, a) for a in DESK]
        for fut in cf.as_completed(futures):
            name, view, err = fut.result()
            if err:
                meeting.errors[name] = err
                emit(f"error:{name}")
            else:
                meeting.views[name] = view
                emit(f"view:{name}")
            emit_analyst(name, view, err)

    # The bear runs last, fed the bull and valuation cases it must rebut.
    bull = meeting.views.get("Bull", "(no bull case was produced)")
    valuation = meeting.views.get("Valuation", "(no valuation was produced)")
    bear_brief = (f"The Bull case to attack:\n{bull}\n\n"
                  f"The Valuation case to attack:\n{valuation}")
    name, view, err = run_analyst(BEAR, bear_brief)
    if err:
        meeting.bear_error = err
        emit("bear_error")
    else:
        meeting.bear = view
        emit("bear")
    emit_analyst("Bear", view, err)

    # No synthesis, no rating. The dissent is the product.
    return meeting
