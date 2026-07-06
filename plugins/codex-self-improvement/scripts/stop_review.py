#!/usr/bin/env python3
"""Codex Stop hook: detect self-improvement signals and optionally continue."""

from __future__ import annotations

from collections import deque
import json
import os
import re
import sys
from typing import Any, Dict, Iterable

from skill_store import load_state, now_iso, record_review_signal, save_state

SIGNAL_RE = re.compile(
    r"(remember|next time|always|don't|do not|wrong|incorrect|broken|improve|"
    r"skill|hook|curat|반드시|항상|다음부터|기억|하지마|하지 말|틀렸|잘못|오류|"
    r"불편|개선|스킬|훅|반복)",
    re.IGNORECASE,
)


def _truthy(value: str | None) -> bool:
    return (value or "").lower() in {"1", "true", "yes", "on"}


def _iter_strings(value: Any, depth: int = 0) -> Iterable[str]:
    if depth > 6:
        return
    if isinstance(value, str):
        if value.strip():
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item, depth + 1)
    elif isinstance(value, dict):
        for key in ("text", "content", "message", "body", "value"):
            if key in value:
                yield from _iter_strings(value[key], depth + 1)


def _row_role(row: Dict[str, Any]) -> str:
    role = row.get("role") or row.get("type")
    message = row.get("message")
    if not role and isinstance(message, dict):
        role = message.get("role") or message.get("type")
    return str(role or "").lower()


def _recent_user_text(transcript_path: str, *, rows_limit: int = 80, char_limit: int = 20_000) -> str:
    if not transcript_path or not os.path.isfile(transcript_path):
        return ""
    rows: deque[Dict[str, Any]] = deque(maxlen=rows_limit)
    try:
        with open(transcript_path, encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except Exception:
        return ""

    parts: list[str] = []
    for row in rows:
        if _row_role(row) != "user":
            continue
        text = " ".join(_iter_strings(row))
        if text:
            parts.append(text)
    return "\n".join(parts)[-char_limit:]


def _signal_source(last_user: str, last_assistant: str, transcript_path: str) -> tuple[bool, str]:
    if SIGNAL_RE.search(last_user):
        return True, "last_user_message"
    if SIGNAL_RE.search(last_assistant):
        return True, "last_assistant_message"
    if SIGNAL_RE.search(_recent_user_text(transcript_path)):
        return True, "transcript_user_messages"
    return False, "none"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    if payload.get("stop_hook_active"):
        return 0

    turn_id = str(payload.get("turn_id") or payload.get("turnId") or "")
    last_assistant = str(payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or "")
    last_user = str(payload.get("last_user_message") or payload.get("lastUserMessage") or "")
    transcript_path = str(payload.get("transcript_path") or payload.get("transcriptPath") or "")

    state = load_state()
    turns = int(state.get("stop_turns") or 0) + 1
    state["stop_turns"] = turns
    signal, signal_source = _signal_source(last_user, last_assistant, transcript_path)
    interval = int(os.environ.get("CODEX_SELF_IMPROVE_INTERVAL", "10") or "10")

    record = {
        "at": now_iso(),
        "turn_id": turn_id,
        "turn_count": turns,
        "signal": signal,
        "signal_source": signal_source,
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
