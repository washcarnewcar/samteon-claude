#!/usr/bin/env python3
"""Codex Stop hook: detect self-improvement signals and optionally continue."""

from __future__ import annotations

import json
import os
import re
import sys

from skill_store import load_state, now_iso, record_review_signal, save_state

SIGNAL_RE = re.compile(
    r"(remember|next time|always|don't|do not|wrong|incorrect|broken|improve|"
    r"skill|hook|curat|반드시|항상|다음부터|기억|하지마|하지 말|틀렸|잘못|오류|"
    r"불편|개선|스킬|훅|반복)",
    re.IGNORECASE,
)


def _truthy(value: str | None) -> bool:
    return (value or "").lower() in {"1", "true", "yes", "on"}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    if payload.get("stop_hook_active"):
        return 0

    turn_id = str(payload.get("turn_id") or payload.get("turnId") or "")
    last_message = str(payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or "")
    transcript_path = str(payload.get("transcript_path") or payload.get("transcriptPath") or "")

    state = load_state()
    turns = int(state.get("stop_turns") or 0) + 1
    state["stop_turns"] = turns
    signal = bool(SIGNAL_RE.search(last_message))
    interval = int(os.environ.get("CODEX_SELF_IMPROVE_INTERVAL", "10") or "10")

    record = {
        "at": now_iso(),
        "turn_id": turn_id,
        "turn_count": turns,
        "signal": signal,
        "transcript_path": transcript_path,
    }
    record_review_signal(record)
    save_state(state)

    auto = _truthy(os.environ.get("CODEX_SELF_IMPROVE_AUTO"))
    if not auto:
        return 0

    if state.get("last_auto_turn_id") == turn_id:
        return 0

    should_continue = signal or (interval > 0 and turns % interval == 0)
    if not should_continue:
        return 0

    state["last_auto_turn_id"] = turn_id
    save_state(state)
    prompt = (
        "Run $codex-self-improvement-review as a short post-turn learning pass. "
        "Inspect the current transcript only for durable workflow or skill lessons. "
        "Patch or create skills only when the lesson is class-level, backed by this thread, "
        "and safe to persist. Prefer dry-run or a concise 'Nothing to save.' if there is no durable signal."
    )
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": prompt,
                "systemMessage": "Codex Self Improvement requested a post-turn review.",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

