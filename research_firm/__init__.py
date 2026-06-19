"""Finance AI Research Agent — a multi-agent investment research desk.

Point it at a ticker and a panel of analyst agents (bull, valuation, macro, a quality
checklist) argues it in parallel; a bear analyst then attacks the bull and valuation cases.
You get the strongest case each way and no blended verdict — the call stays with you.

    from research_firm import hold_meeting
    meeting = hold_meeting("AAPL")
    print(meeting.views["Bull"])
    print(meeting.bear)
"""
from research_firm.analysts import BEAR, DESK, Analyst
from research_firm.engine import DEFAULT_MODEL, Meeting, hold_meeting

__version__ = "0.1.0"
__all__ = ["hold_meeting", "Meeting", "Analyst", "DESK", "BEAR", "DEFAULT_MODEL"]
