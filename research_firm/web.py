"""A small public web demo for the research desk.

A FastAPI app that runs `hold_meeting()` and streams the debate live over Server-Sent Events:
the analyst desk lands card-by-card, then the Bear, then a "no verdict" marker. One self-contained
cream page consumes the stream.

It is a PUBLIC, keyed-on-the-host's-own-credit demo, so it is built to *never* error and *never*
run up a bill:

  * a per-IP hourly rate limit and a global daily cap (both env-tunable),
  * a pre-baked saved run served whenever there is no API key, the caller is over a limit, or the
    live meeting raises — so the link always returns a polished result.

Nothing here is investment advice, and there is deliberately no verdict.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import deque
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from research_firm import market
from research_firm.analysts import DESK
from research_firm.engine import DEFAULT_MODEL, hold_meeting

load_dotenv()

_HERE = Path(__file__).parent
_INDEX = _HERE / "web_static" / "index.html"
_EXAMPLES = _HERE / "examples"

# Guardrail defaults are tuned for a host running on a tightly capped key (~$5/day); the hard cap
# on the key is the real backstop, these just keep the link from getting hammered. All env-tunable.
RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "3"))
DAILY_CAP = int(os.getenv("DAILY_CAP", "60"))

# Small per-card delay (seconds) when replaying a saved run, so the cached path animates like a live
# one rather than dumping every card at once.
_REPLAY_DELAY = float(os.getenv("REPLAY_DELAY", "0.45"))

app = FastAPI(title="Finance AI Research Agent", docs_url=None, redoc_url=None)


# --------------------------------------------------------------------------- guardrails
class _Limiter:
    """In-memory per-IP hourly window + a global daily counter. A single instance (Railway runs one)
    makes a process-local dict sufficient; nothing here needs to survive a restart."""

    def __init__(self, per_hour: int, daily_cap: int) -> None:
        self.per_hour = per_hour
        self.daily_cap = daily_cap
        self._hits: dict[str, deque[float]] = {}
        self._day = date.min
        self._day_count = 0
        self._lock = threading.Lock()

    def _roll_day(self, today: date) -> None:
        if today != self._day:
            self._day = today
            self._day_count = 0

    def check(self, ip: str, *, now: float, today: date) -> tuple[bool, str]:
        """Return (allowed, reason). `reason` is "" when allowed, else why the saved run is served."""
        with self._lock:
            self._roll_day(today)
            if self.daily_cap and self._day_count >= self.daily_cap:
                return False, "daily-cap"
            window = self._hits.setdefault(ip, deque())
            cutoff = now - 3600
            while window and window[0] < cutoff:
                window.popleft()
            if self.per_hour and len(window) >= self.per_hour:
                return False, "rate-limit"
            window.append(now)
            self._day_count += 1
            return True, ""


_limiter = _Limiter(RATE_LIMIT_PER_HOUR, DAILY_CAP)


def _client_ip(request: Request) -> str:
    """Railway (and most PaaS) sit behind a proxy, so trust the first X-Forwarded-For hop."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------- SSE helpers
def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


_DONE_NOTE = (
    "No verdict. No rating. The strongest case each way is above — the decision is yours."
)


def _load_example(ticker: str) -> dict[str, Any]:
    """A committed saved run for `ticker`, falling back to AAPL so any input returns something.
    Read fresh each time (small files); the `meta` note already tells the user it is a saved run."""
    candidate = _EXAMPLES / f"{ticker.upper()}.json"
    path = candidate if candidate.exists() else _EXAMPLES / "AAPL.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _cached_note(reason: str) -> str:
    return {
        "no-key": "Demo running without a live key — showing a saved run.",
        "rate-limit": "You've hit the hourly limit — showing a saved run.",
        "daily-cap": "Demo at capacity for today — showing a saved run.",
        "error": "Live run hit a snag — showing a saved run.",
    }.get(reason, "Showing a saved run.")


async def _replay_cached(ticker: str, reason: str):
    """Stream a saved run with the same event shape as a live one, lightly paced."""
    data = _load_example(ticker)
    yield _sse("meta", {"cached": True, "reason": reason, "note": _cached_note(reason)})
    yield _sse("profile", data.get("profile") or {"ticker": ticker})
    await asyncio.sleep(_REPLAY_DELAY)
    views = data.get("views") or {}
    errors = data.get("errors") or {}
    for analyst in DESK:  # stable desk order
        name = analyst.name
        if name in views:
            yield _sse("analyst", {"name": name, "view": views[name], "error": None})
        elif name in errors:
            yield _sse("analyst", {"name": name, "view": None, "error": errors[name]})
        await asyncio.sleep(_REPLAY_DELAY)
    yield _sse("bear", {"view": data.get("bear"), "error": data.get("bear_error")})
    await asyncio.sleep(_REPLAY_DELAY)
    yield _sse("done", {"note": _DONE_NOTE})


async def _run_live(ticker: str, model: str):
    """Run a real meeting in a worker thread and bridge its sync content hook to this async stream
    via a thread-safe queue. Falls back to the saved run if the meeting raises."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

    def push(event: str, data: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, data))

    def on_analyst(name: str, view: str | None, error: str | None) -> None:
        if name == "Bear":
            push("bear", {"view": view, "error": error})
        else:
            push("analyst", {"name": name, "view": view, "error": error})

    def work() -> None:
        try:
            profile = market.snapshot(ticker)
            push("profile", profile or {"ticker": ticker})
            hold_meeting(ticker, model=model, fetch=lambda _t: profile, on_analyst=on_analyst)
            push("done", {"note": _DONE_NOTE})
        except Exception:  # noqa: BLE001 — never let a live failure error the stream; degrade to cached
            push("__fallback__", {})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    asyncio.create_task(asyncio.to_thread(work))

    while True:
        item = await queue.get()
        if item is None:
            break
        event, data = item
        if event == "__fallback__":
            async for frame in _replay_cached(ticker, "error"):
                yield frame
            break
        yield _sse(event, data)


# --------------------------------------------------------------------------- routes
@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "model": DEFAULT_MODEL})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_INDEX, media_type="text/html")


@app.get("/api/meeting")
async def meeting(request: Request, ticker: str = "") -> StreamingResponse:
    ticker = (ticker or "").strip().upper()[:8]

    async def stream():
        if not ticker:
            # NB: not named "error" — EventSource reserves that for connection failures.
            yield _sse("error_msg", {"message": "Enter a ticker, e.g. AAPL."})
            yield _sse("done", {"note": _DONE_NOTE})
            return

        # No key at all -> always serve the saved run (covers local-without-key and a misconfigured
        # deploy). Otherwise enforce the per-IP + daily guardrails before spending anything.
        if not os.getenv("ANTHROPIC_API_KEY"):
            async for frame in _replay_cached(ticker, "no-key"):
                yield frame
            return

        allowed, reason = _limiter.check(
            _client_ip(request), now=time.time(), today=date.today()
        )
        if not allowed:
            async for frame in _replay_cached(ticker, reason):
                yield frame
            return

        async for frame in _run_live(ticker, DEFAULT_MODEL):
            yield frame

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # disable proxy buffering so cards arrive live
        "Connection": "keep-alive",
    }
    return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)
