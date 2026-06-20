"""Tests for the clean-room DCF model. Pure math — no network, no API key."""
from __future__ import annotations

from research_firm import valuation as V


def _profile(**over):
    p = {
        "free_cash_flow": 1.0e10, "shares_outstanding": 1.0e9,
        "total_debt": 2.0e9, "total_cash": 5.0e9, "market_cap": 3.0e11,
        "beta": 1.1, "currency": "USD", "price": 250.0, "revenue_growth": 0.09,
    }
    p.update(over)
    return p


def test_gordon_growth_identity():
    # When near-term growth equals terminal growth, the two-stage DCF must collapse to the closed
    # form of a growing perpetuity: fcf0*(1+g)/(r-g), per share, net of debt. This pins the math.
    d = V.discounted_cash_flow(
        {"free_cash_flow": 100.0, "shares_outstanding": 10.0, "total_debt": 0.0,
         "total_cash": 0.0, "currency": "USD"},
        growth=0.025, discount=0.09, terminal_growth=0.025)
    expected = (100.0 * 1.025 / (0.09 - 0.025)) / 10.0
    assert abs(d.value_base - expected) < 1e-6


def test_net_debt_reduces_value():
    no_debt = V.discounted_cash_flow(_profile(total_debt=0.0, total_cash=0.0),
                                     growth=0.06, discount=0.09)
    with_debt = V.discounted_cash_flow(_profile(total_debt=5.0e10, total_cash=0.0),
                                       growth=0.06, discount=0.09)
    assert with_debt.value_base < no_debt.value_base


def test_monotonicity():
    base = dict(fcf0=100, growth=0.05, terminal_growth=0.025, years=10, net_debt=0, shares=10)
    cheap_rate = V._two_stage_per_share(discount=0.08, **base)
    dear_rate = V._two_stage_per_share(discount=0.11, **base)
    assert dear_rate < cheap_rate                      # higher discount -> lower value
    slow = V._two_stage_per_share(fcf0=100, growth=0.03, terminal_growth=0.025, discount=0.09,
                                  years=10, net_debt=0, shares=10)
    fast = V._two_stage_per_share(fcf0=100, growth=0.09, terminal_growth=0.025, discount=0.09,
                                  years=10, net_debt=0, shares=10)
    assert fast > slow                                 # higher growth -> higher value


def test_range_brackets_base():
    d = V.discounted_cash_flow(_profile())
    assert d.value_low <= d.value_base <= d.value_high
    assert d.value_low < d.value_high                  # a real spread, not a point


def test_unavailable_when_no_positive_fcf():
    assert V.discounted_cash_flow(_profile(free_cash_flow=-1.0e9)) is None
    assert V.discounted_cash_flow(_profile(free_cash_flow=None)) is None
    assert V.discounted_cash_flow(_profile(shares_outstanding=None)) is None


def test_format_and_public_dict():
    d = V.discounted_cash_flow(_profile())
    text = V.format_dcf(d)
    assert "Discounted-cash-flow model" in text and "Intrinsic value per share" in text
    assert "RANGE" in text                              # tells the analyst to give a band
    pub = V.public_dict(d)
    assert pub["available"] is True
    assert pub["value_low"] <= pub["value_base"] <= pub["value_high"]
    assert len(pub["grid"]) == 3 and len(pub["grid"][0]) == 3

    none_text = V.format_dcf(None)
    assert "not run" in none_text                       # degrades with an explanation
    assert V.public_dict(None)["available"] is False
