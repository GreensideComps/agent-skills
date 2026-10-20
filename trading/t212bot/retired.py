"""Branch retirement (owner decision O10, 20 Oct 2026).

This branch holds the retired discretionary intraday / 100% LQQ3 bot. It is kept
only as an audit record. Every entry point that could trade refuses here: the CLI,
Bot.run, decide, and any non-GET broker request. The flag is a code constant on
purpose: deleting a file or editing strategy.json cannot re-enable trading; only a
reviewed commit that changes this line can.
"""
from __future__ import annotations

from .config import SafetyError

BRANCH_RETIRED = True
MESSAGE = ("this branch's bot is retired (owner decision O10, 2026-10-20); "
           "it is kept for audit only and cannot trade")


def refuse_if_retired(what: str) -> None:
    if BRANCH_RETIRED:
        raise SafetyError(f"{what} refused: {MESSAGE}")
