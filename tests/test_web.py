"""Web-layer tests. These need FastAPI + httpx (the `[dev]`/`[web]` extras); they skip cleanly if
fastapi isn't installed, so the core hermetic suite still runs on a bare install.

The key path under test is the never-errors guarantee: with no `ANTHROPIC_API_KEY`, a request must
still return a complete, well-formed SSE meeting from the committed saved run."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from research_firm import web  # noqa: E402


def _parse_sse(body: str) -> list[tuple[str, str]]:
    """Flatten an SSE body into [(event, data), ...]."""
    events: list[tuple[str, str]] = []
    event = "message"
    for line in body.splitlines():
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            events.append((event, line[len("data:"):].strip()))
            event = "message"
    return events


def test_index_serves_html():
    with TestClient(web.app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "Finance AI Research Agent" in r.text
        assert "text/html" in r.headers["content-type"]


def test_health_ok():
    with TestClient(web.app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["model"] == "claude-sonnet-4-6"   # the model id stays put


def test_keyless_request_serves_cached_run(monkeypatch):
    # No key -> must serve the saved run (cached fallback), never error.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(web, "_REPLAY_DELAY", 0.0)   # don't sleep through the test
    with TestClient(web.app) as client:
        r = client.get("/api/meeting?ticker=AAPL")
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        events = _parse_sse(r.text)
        names = [e for e, _ in events]
        assert "meta" in names      # the "showing a saved run" marker
        assert "profile" in names
        assert "valuation_model" in names   # the DCF model rides along
        assert names.count("analyst") >= 1
        assert "bear" in names
        assert names[-1] == "done"  # always closes cleanly
        # the cached AAPL run carries a real DCF payload
        import json as _json
        vm = next(_json.loads(d) for e, d in events if e == "valuation_model")
        assert vm["available"] is True and vm["value_low"] <= vm["value_high"]


def test_search_endpoint(monkeypatch):
    web._SEARCH_CACHE.clear()
    monkeypatch.setattr(web, "_yahoo_search",
                        lambda q: [{"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"}])
    with TestClient(web.app) as client:
        assert client.get("/api/search?q=a").json()["results"] == []   # too short -> no upstream call
        body = client.get("/api/search?q=apple").json()
        assert body["results"][0] == {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"}


def test_empty_ticker_is_handled(monkeypatch):
    monkeypatch.setattr(web, "_REPLAY_DELAY", 0.0)
    with TestClient(web.app) as client:
        r = client.get("/api/meeting?ticker=")
        assert r.status_code == 200
        names = [e for e, _ in _parse_sse(r.text)]
        assert "error_msg" in names and names[-1] == "done"


def test_rate_limit_falls_back_to_cached(monkeypatch):
    # With a key present but the limiter denying the request, the live path is skipped and the saved
    # run is served instead — proving the guardrail degrades gracefully rather than spending.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")
    monkeypatch.setattr(web, "_REPLAY_DELAY", 0.0)
    monkeypatch.setattr(web._limiter, "check", lambda *a, **k: (False, "rate-limit"))
    with TestClient(web.app) as client:
        r = client.get("/api/meeting?ticker=NVDA")
        events = _parse_sse(r.text)
        meta = next((d for e, d in events if e == "meta"), "")
        assert "rate-limit" in meta            # served because of the limit, not a live call
        assert [e for e, _ in events][-1] == "done"
