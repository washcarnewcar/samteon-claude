#!/usr/bin/env python3
"""Codex PostToolUse hook: record lightweight tool telemetry."""

from __future__ import annotations

import json
import sys

from skill_store import record_tool_use


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or payload.get("name") or "unknown")
    try:
        record_tool_use(tool_name, payload if isinstance(payload, dict) else {})
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

