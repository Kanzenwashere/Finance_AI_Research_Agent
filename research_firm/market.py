"""Best-effort market-data snapshot for a ticker.

Wraps yfinance to pull a small, sane set of facts (price, sector, a few multiples, a one-line
business summary) that give the analysts something real to reason about. Returns {} on any
failure so the meeting still runs and degrades gracefully rather than crashing.
"""
from __future__ import annotations

from typing import Any

_CACHE: dict[str, dict[str, Any]] = {}


def snapshot(ticker: str) -> dict[str, Any]:
    """A compact, ground-truth profile for `ticker`. Cached per process; {} if unavailable."""
    t = (ticker or "").strip().upper()
    if not t:
        return {}
    if t in _CACHE:
        return _CACHE[t]
    profile: dict[str, Any] = {}
    try:
        import yfinance as yf
        info = yf.Ticker(t).info or {}
        profile = {
            "ticker": t,
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "currency": info.get("currency"),
            "market_cap": info.get("marketCap"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "profit_margin": info.get("profitMargins"),
            "revenue_growth": info.get("revenueGrowth"),
            "summary": (info.get("longBusinessSummary") or "")[:700],
        }
    except Exception:  # noqa: BLE001 — data is best-effort; a failure must not sink the meeting
        profile = {}
    _CACHE[t] = profile
    return profile


def format_context(ticker: str, profile: dict[str, Any]) -> str:
    """Render a profile into a short text block the analyst prompts can consume."""
    if not profile:
        return (f"Ticker: {ticker}\n(No market data available — reason from general knowledge "
                f"of the company and say so.)")

    def money(v: Any) -> str:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return "n/a"
        for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
            if abs(v) >= size:
                return f"{v / size:.1f}{unit}"
        return f"{v:.0f}"

    def pct(v: Any) -> str:
        try:
            return f"{float(v) * 100:.1f}%"
        except (TypeError, ValueError):
            return "n/a"

    rows = [
        f"Ticker: {ticker}",
        f"Name: {profile.get('name') or 'n/a'}",
        f"Sector / industry: {profile.get('sector') or 'n/a'} / {profile.get('industry') or 'n/a'}",
        f"Price: {profile.get('price') or 'n/a'} {profile.get('currency') or ''}".strip(),
        f"Market cap: {money(profile.get('market_cap'))}",
        f"Trailing P/E: {profile.get('trailing_pe') or 'n/a'} | Forward P/E: {profile.get('forward_pe') or 'n/a'}",
        f"Profit margin: {pct(profile.get('profit_margin'))} | Revenue growth: {pct(profile.get('revenue_growth'))}",
        f"Business: {profile.get('summary') or 'n/a'}",
    ]
    return "\n".join(rows)
