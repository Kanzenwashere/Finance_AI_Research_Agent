"""Command-line interface.

    finance-research AAPL
    finance-research --model claude-opus-4-8 NVDA
    finance-research --json TSLA > meeting.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from research_firm.analysts import BEAR, DESK
from research_firm.engine import DEFAULT_MODEL, Meeting, hold_meeting


class C:
    _on = sys.stdout.isatty() and not os.getenv("NO_COLOR")
    DIM = "\033[2m" if _on else ""
    BOLD = "\033[1m" if _on else ""
    CYAN = "\033[36m" if _on else ""
    RED = "\033[31m" if _on else ""
    RESET = "\033[0m" if _on else ""


def _rule(char: str = "─", width: int = 70) -> str:
    return char * width


def _render(meeting: Meeting) -> None:
    p = meeting.profile
    head = f"{meeting.ticker}" + (f" — {p['name']}" if p.get("name") else "")
    print(f"\n  {C.BOLD}FIRM MEETING · {head}{C.RESET}")
    if p.get("price"):
        print(f"  {C.DIM}{p.get('price')} {p.get('currency') or ''} · "
              f"{p.get('sector') or 'n/a'}{C.RESET}")
    print(_rule())

    for a in DESK:  # stable order, not completion order
        header = f"{C.BOLD}── {a.name} {_rule('─', max(1, 66 - len(a.name)))}{C.RESET}"
        if a.name in meeting.errors:
            print(f"\n{header}\n{C.DIM}(unavailable — {meeting.errors[a.name]}){C.RESET}")
        elif a.name in meeting.views:
            print(f"\n{header}\n{meeting.views[a.name]}")

    print(f"\n{C.RED}{_rule('═')}{C.RESET}")
    print(f"  {C.BOLD}{C.RED}{BEAR.name} — the case against{C.RESET}")
    print(f"{C.RED}{_rule('═')}{C.RESET}")
    if meeting.bear:
        print(meeting.bear)
    else:
        print(f"{C.DIM}(bear unavailable — {meeting.bear_error}){C.RESET}")

    print(f"\n{_rule()}")
    print(f"  {C.DIM}No verdict. No rating. The strongest case each way is above —\n"
          f"  the decision is yours.{C.RESET}\n")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="finance-research",
        description="Run a multi-agent research meeting on a ticker — bull, valuation, macro, "
                    "a quality checklist, and an adversarial bear. No verdict; you decide.")
    parser.add_argument("ticker", help="the stock ticker to research, e.g. AAPL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"model id (default {DEFAULT_MODEL})")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="emit the raw meeting as JSON instead of formatted text")
    args = parser.parse_args(argv)

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY first (export it or add it to a .env file).", file=sys.stderr)
        return 1

    def on_event(tag: str) -> None:
        if args.as_json:
            return
        kind, _, name = tag.partition(":")
        if kind == "view":
            print(f"  {C.CYAN}▸ {name} weighed in.{C.RESET}")
        elif kind == "error":
            print(f"  {C.DIM}▸ {name} unavailable.{C.RESET}")
        elif tag == "bear":
            print(f"  {C.RED}▸ Bear is making the case against…{C.RESET}")

    meeting = hold_meeting(args.ticker, model=args.model, on_event=on_event)

    if args.as_json:
        print(json.dumps(meeting.to_dict(), indent=2, ensure_ascii=False))
    else:
        _render(meeting)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
