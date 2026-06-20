"""A transparent, clean-room discounted-cash-flow model.

This is a deliberately standard two-stage DCF — the kind in any corporate-finance textbook:
project free cash flow, discount it at an estimated WACC, add a terminal value, net out debt,
divide by shares. It is **whole-company only** — it never decomposes a business into segments — and
it produces an intrinsic-value *range*, not a single target, by flexing the two most material
assumptions (the discount rate and near-term FCF growth) across a small grid.

Everything degrades gracefully. If trailing free cash flow is missing or negative, or shares aren't
known, a DCF doesn't mean anything (financials, deeply unprofitable names, data gaps) — so the model
returns `None` and the desk falls back to multiples-based reasoning rather than printing a fake
number.

Defaults are conservative, current-ish, and fully stated so the output can be audited:
  * risk-free rate 4.3%, equity risk premium 5.0% (cost of equity via CAPM)
  * pre-tax cost of debt 5.5%, tax rate 21%
  * 10-year explicit horizon, 2.5% terminal growth
Near-term FCF growth is taken from the company's revenue growth, clamped to a sane band.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- model assumptions (all overridable; surfaced in the output so nothing is hidden) ---
RISK_FREE = 0.043
EQUITY_RISK_PREMIUM = 0.050
COST_OF_DEBT = 0.055
TAX_RATE = 0.21
HORIZON_YEARS = 10
TERMINAL_GROWTH = 0.025
DEFAULT_GROWTH = 0.06            # used when revenue growth is unavailable
GROWTH_FLOOR = TERMINAL_GROWTH + 0.005
GROWTH_CEIL = 0.15               # FCF can't out-compound the economy forever
# half-widths used to build the intrinsic-value range
DISCOUNT_STEP = 0.015
GROWTH_STEP = 0.03


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # reject NaN


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class DCF:
    """One DCF run: the assumptions, the per-share base value, the range, and a sensitivity grid."""
    currency: str | None
    fcf: float
    net_debt: float
    shares: float
    discount_rate: float
    growth: float
    terminal_growth: float
    years: int
    value_base: float
    value_low: float
    value_high: float
    price: float | None
    grid_discounts: list[float]
    grid_growths: list[float]
    grid: list[list[float]]  # grid[i][j] = per-share value at grid_discounts[i], grid_growths[j]

    def to_public_dict(self) -> dict[str, Any]:
        """JSON-able payload for the web layer (rounded for display)."""
        r = lambda x: round(x, 2) if x is not None else None
        return {
            "available": True,
            "currency": self.currency,
            "fcf": self.fcf,
            "net_debt": self.net_debt,
            "shares": self.shares,
            "discount_rate": self.discount_rate,
            "growth": self.growth,
            "terminal_growth": self.terminal_growth,
            "years": self.years,
            "value_base": r(self.value_base),
            "value_low": r(self.value_low),
            "value_high": r(self.value_high),
            "price": r(self.price),
            "grid_discounts": self.grid_discounts,
            "grid_growths": self.grid_growths,
            "grid": [[r(v) for v in row] for row in self.grid],
        }


def _two_stage_per_share(fcf0: float, growth: float, terminal_growth: float, discount: float,
                         years: int, net_debt: float, shares: float) -> float:
    """Standard two-stage DCF, per share.

    Stage 1: FCF grows from `growth` fading linearly to `terminal_growth` over `years`. Stage 2: a
    Gordon-growth terminal value at `terminal_growth`. Note the identity used in tests: when
    growth == terminal_growth this collapses to the growing perpetuity fcf0*(1+g)/(discount-g).
    """
    discount = max(discount, terminal_growth + 0.01)  # keeps (discount - terminal_growth) > 0
    pv_stage1 = 0.0
    fcf = fcf0
    for t in range(1, years + 1):
        g_t = growth + (terminal_growth - growth) * (t - 1) / max(1, years - 1)
        fcf = fcf * (1 + g_t)
        pv_stage1 += fcf / (1 + discount) ** t
    terminal_value = fcf * (1 + terminal_growth) / (discount - terminal_growth)
    pv_terminal = terminal_value / (1 + discount) ** years
    enterprise_value = pv_stage1 + pv_terminal
    equity_value = enterprise_value - net_debt
    return equity_value / shares


def _wacc(beta: float | None, market_cap: float | None, total_debt: float | None) -> float:
    """A plain CAPM-based WACC. Falls back to cost of equity when capital weights are unknown."""
    b = beta if beta is not None else 1.0
    cost_of_equity = RISK_FREE + b * EQUITY_RISK_PREMIUM
    after_tax_cost_of_debt = COST_OF_DEBT * (1 - TAX_RATE)
    e = market_cap if (market_cap and market_cap > 0) else None
    d = total_debt if (total_debt and total_debt > 0) else 0.0
    if e is None:
        return cost_of_equity
    w_e = e / (e + d)
    w_d = d / (e + d)
    return w_e * cost_of_equity + w_d * after_tax_cost_of_debt


def discounted_cash_flow(profile: dict[str, Any], *,
                         growth: float | None = None,
                         discount: float | None = None,
                         terminal_growth: float = TERMINAL_GROWTH,
                         years: int = HORIZON_YEARS) -> DCF | None:
    """Build a DCF from a market profile, or return None if the inputs can't support one.

    `growth` and `discount` can be pinned (tests, what-ifs); otherwise they're derived from the
    profile (revenue growth, beta, capital structure)."""
    fcf = _num(profile.get("free_cash_flow"))
    shares = _num(profile.get("shares_outstanding"))
    if fcf is None or fcf <= 0 or shares is None or shares <= 0:
        return None  # no meaningful FCF or share count -> a DCF would be fiction

    total_debt = _num(profile.get("total_debt")) or 0.0
    total_cash = _num(profile.get("total_cash")) or 0.0
    net_debt = total_debt - total_cash
    market_cap = _num(profile.get("market_cap"))
    price = _num(profile.get("price"))

    base_discount = discount if discount is not None else _wacc(
        _num(profile.get("beta")), market_cap, total_debt)
    # Floor leaves room for the low end of the grid (base - DISCOUNT_STEP) to stay safely above the
    # terminal growth rate, so the displayed grid rates always match the rates actually discounted.
    base_discount = _clamp(base_discount, terminal_growth + 0.04, 0.20)

    if growth is not None:
        base_growth = growth
    else:
        rev_growth = _num(profile.get("revenue_growth"))
        base_growth = _clamp(rev_growth if rev_growth is not None else DEFAULT_GROWTH,
                             GROWTH_FLOOR, GROWTH_CEIL)

    discounts = [round(base_discount - DISCOUNT_STEP, 4), round(base_discount, 4),
                 round(base_discount + DISCOUNT_STEP, 4)]
    growths = [round(max(GROWTH_FLOOR, base_growth - GROWTH_STEP), 4), round(base_growth, 4),
               round(min(GROWTH_CEIL, base_growth + GROWTH_STEP), 4)]

    grid = [[_two_stage_per_share(fcf, g, terminal_growth, d, years, net_debt, shares)
             for g in growths] for d in discounts]
    flat = [v for row in grid for v in row]
    value_base = _two_stage_per_share(fcf, base_growth, terminal_growth, base_discount,
                                      years, net_debt, shares)

    return DCF(
        currency=profile.get("currency"),
        fcf=fcf, net_debt=net_debt, shares=shares,
        discount_rate=base_discount, growth=base_growth, terminal_growth=terminal_growth,
        years=years, value_base=value_base, value_low=min(flat), value_high=max(flat),
        price=price, grid_discounts=discounts, grid_growths=growths, grid=grid,
    )


def _money(v: float | None) -> str:
    if v is None:
        return "n/a"
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(v) >= size:
            return f"{v / size:.1f}{unit}"
    return f"{v:.0f}"


def format_dcf(dcf: DCF | None) -> str:
    """A text block describing the model, for the Valuation analyst's context. Empty if no DCF."""
    if dcf is None:
        return ("DCF model: not run — trailing free cash flow is unavailable or not positive, so a "
                "cash-flow valuation would be meaningless here. Reason from multiples instead and "
                "say a DCF isn't applicable.")
    cur = dcf.currency or ""
    lines = [
        "--- Discounted-cash-flow model (standard two-stage, whole-company; computed for you) ---",
        f"Trailing free cash flow: {_money(dcf.fcf)} {cur}".strip(),
        f"Net debt: {_money(dcf.net_debt)} {cur} | Shares out: {_money(dcf.shares)}".strip(),
        f"Assumptions: WACC {dcf.discount_rate * 100:.1f}%, near-term FCF growth "
        f"{dcf.growth * 100:.1f}% fading to {dcf.terminal_growth * 100:.1f}% terminal over "
        f"{dcf.years} years.",
        f"Intrinsic value per share: base ~{dcf.value_base:.0f} {cur}, range "
        f"~{dcf.value_low:.0f}–{dcf.value_high:.0f} {cur} (flexing the discount rate ±"
        f"{DISCOUNT_STEP * 100:.1f}pts and growth ±{GROWTH_STEP * 100:.0f}pts).".strip(),
    ]
    if dcf.price is not None:
        where = ("below" if dcf.price < dcf.value_low else
                 "above" if dcf.price > dcf.value_high else "within")
        lines.append(f"Current price {dcf.price:.0f} {cur} sits {where} that range.".strip())
    lines.append("Use this as the spine of your valuation. State your conclusion as an intrinsic-"
                 "value RANGE grounded in these numbers (and where price sits in it) — never a "
                 "single target price or a buy/sell call. Challenge the assumptions if they look off.")
    return "\n".join(lines)


def public_dict(dcf: DCF | None, reason: str = "") -> dict[str, Any]:
    """JSON-able payload for the web layer, for both the available and unavailable cases."""
    if dcf is None:
        return {"available": False, "reason": reason or "no positive trailing free cash flow"}
    return dcf.to_public_dict()
