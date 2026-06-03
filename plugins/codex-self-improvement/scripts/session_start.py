#!/usr/bin/env python3
"""Codex SessionStart hook: inject a tiny plugin status note."""

from __future__ import annotations

import json
import sys

from skill_store import status


def main() -> int:
    try:
        st = status()
        note = (
            "Codex Self Improvement is active. Use $codex-self-improvement-review "
            "for durable skill updates and $codex-skill-curator for dry-run skill maintenance. "
            f"Auto-continue is {'on' if st.get('auto_continue') else 'off'}."
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": note,
                    }
                },
                ensure_ascii=False,
            )
        )
    except Exception as exc:
        print(json.dumps({"systemMessage": f"Self-improvement status unavailable: {exc}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

