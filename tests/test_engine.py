"""Hermetic tests — the Anthropic client and the market feed are faked, so these run with no
network and no API key."""
from __future__ import annotations

from anthropic import AnthropicError

from research_firm import Meeting, hold_meeting
from research_firm.analysts import BEAR, DESK

PROFILE = {"ticker": "TEST", "name": "Test Corp", "price": 100, "currency": "USD",
           "sector": "Technology", "summary": "A test company."}


def fake_fetch(_ticker: str) -> dict:
    return dict(PROFILE)


class _Msg:
    def __init__(self, text: str):
        self.content = [type("Block", (), {"text": text})()]


class _EmptyMsg:
    content: list = []   # an empty / non-text reply, like a refusal


class _Messages:
    def __init__(self, outer: "FakeClient"):
        self._outer = outer

    def create(self, *, model, max_tokens, system, messages, timeout):
        self._outer.calls.append({"system": system, "user": messages[0]["content"]})
        if any(tok in system for tok in self._outer.fail_on):
            raise AnthropicError("simulated failure")
        if any(tok in system for tok in self._outer.empty_on):
            return _EmptyMsg()
        # Echo the analyst role (first word of the mandate's "You are the X") for assertions.
        return _Msg(f"view::{system[:40]}")


class FakeClient:
    def __init__(self, fail_on=None, empty_on=None):
        self.calls: list[dict] = []
        self.fail_on = set(fail_on or [])
        self.empty_on = set(empty_on or [])
        self.messages = _Messages(self)


def test_full_desk_runs_and_bear_fires():
    client = FakeClient()
    m = hold_meeting("TEST", client=client, fetch=fake_fetch)
    assert set(m.views) == {a.name for a in DESK}     # every desk analyst produced a view
    assert m.errors == {}
    assert m.bear is not None and m.bear_error is None
    assert m.profile["name"] == "Test Corp"           # market snapshot attached


def test_one_analyst_failure_is_isolated():
    client = FakeClient(fail_on={"Macro analyst"})    # the Macro mandate contains "Macro analyst"
    m = hold_meeting("TEST", client=client, fetch=fake_fetch)
    assert "Macro" in m.errors
    assert "Bull" in m.views and "Valuation" in m.views
    assert m.bear is not None                          # bear still runs on the survivors


def test_empty_reply_is_captured_not_raised():
    client = FakeClient(empty_on={"Bull analyst"})
    m = hold_meeting("TEST", client=client, fetch=fake_fetch)
    assert "Bull" in m.errors                           # empty reply -> failed slot, no crash
    assert "Valuation" in m.views


def test_bear_is_fed_the_bull_and_valuation_cases():
    client = FakeClient()
    hold_meeting("TEST", client=client, fetch=fake_fetch)
    bear_call = next(c for c in client.calls if c["system"].startswith(BEAR.mandate[:40]))
    assert "The Bull case to attack:" in bear_call["user"]
    assert "The Valuation case to attack:" in bear_call["user"]


def test_meeting_has_no_verdict_field():
    # The whole point: the firm never collapses the dissent into a rating.
    assert "verdict" not in Meeting.__dataclass_fields__
    assert "rating" not in Meeting.__dataclass_fields__


def test_progress_events_emitted():
    client = FakeClient(fail_on={"Macro analyst"})
    seen: list[str] = []
    hold_meeting("TEST", client=client, fetch=fake_fetch, on_event=seen.append)
    assert "view:Bull" in seen and "error:Macro" in seen and "bear" in seen


def test_on_analyst_streams_content_for_desk_and_bear():
    # The content hook fires once per desk analyst AND once for the Bear, carrying (name, view, err).
    client = FakeClient(fail_on={"Macro analyst"})
    got: list[tuple[str, str | None, str | None]] = []
    hold_meeting("TEST", client=client, fetch=fake_fetch,
                 on_analyst=lambda name, view, err: got.append((name, view, err)))
    by_name = {name: (view, err) for name, view, err in got}
    assert {a.name for a in DESK} | {"Bear"} <= set(by_name)   # every seat + the bear reported
    assert by_name["Bull"][0] and by_name["Bull"][1] is None   # a view, no error
    assert by_name["Macro"][0] is None and by_name["Macro"][1] is not None  # failed slot -> error
    assert by_name["Bear"][0] is not None                      # bear streamed its content
