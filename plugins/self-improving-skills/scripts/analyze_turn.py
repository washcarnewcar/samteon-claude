#!/usr/bin/env python3
"""Stop-hook analyzer for the self-improving-skills plugin.

Reads the Claude Code Stop-hook payload on stdin, measures how many tool calls
have accumulated since the last skill-distillation "anchor", and emits a
Stop-hook decision on stdout. If the work since the last distillation looks
substantial enough and nothing has been distilled, it BLOCKs and instructs the
agent to delegate to the skill-distiller subagent. Otherwise it APPROVEs.

Design notes — every one of these avoids a confirmed failure mode of the
sibling dev-log hook (which never fired across 396 real transcripts):

  * Tool calls are detected via the REAL transcript shape — an `assistant` row
    whose `message.content[]` contains `{"type":"tool_use","name":...}`.
    (dev-log grepped for `"tool":"Edit"`, which matches 0 transcripts; the real
    key is `"name":"Edit"`.)
  * "Already distilled?" is decided by an ACTUAL action — a Task delegation to
    skill-distiller, or a Write/Edit of a SKILL.md under ~/.claude/skills — not
    by a substring match on the word "distill"/the plugin name, which would
    self-trip because the plugin's own name/paths are injected into every
    transcript.
  * The block decision is emitted as JSON on STDOUT with exit 0 (the contract
    Claude Code actually parses), NOT on stderr with exit 2.
  * `stop_hook_active` is honored as a loop guard so we never re-block our own
    block.
  * Any error fails safe to APPROVE — the hook must never wedge a session shut.

Config:
  SIS_DISTILL_THRESHOLD  tool calls since last distill required to nudge (default 12)
  SIS_MIN_FILE_EDITS     min real file edits (Edit/Write/MultiEdit/NotebookEdit)
                         since last distill, so pure read/search turns don't nudge (default 2)
"""

import json
import os
import sys
from typing import NoReturn

SKILL_MARKER = "skill-distiller"
EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def emit(obj) -> NoReturn:
    """Write a Stop-hook decision to stdout and exit 0."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(0)


def approve() -> NoReturn:
    emit({"decision": "approve"})


def _int_env(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _tool_uses(row):
    """Yield tool_use blocks from an assistant row (real transcript shape)."""
    if not isinstance(row, dict) or row.get("type") != "assistant":
        return
    msg = row.get("message")
    if not isinstance(msg, dict):
        return
    content = msg.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield block


def _is_skill_path(file_path):
    """True if a path is a SKILL.md inside a ~/.claude/skills tree."""
    norm = str(file_path or "").replace("\\", "/")
    return "/.claude/skills/" in norm and norm.endswith("SKILL.md")


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        approve()

    # Loop guard: never re-block inside the same Stop cycle.
    if payload.get("stop_hook_active"):
        approve()

    path = payload.get("transcript_path") or ""
    if not path or not os.path.isfile(path):
        approve()

    threshold = _int_env("SIS_DISTILL_THRESHOLD", 12)
    min_edits = _int_env("SIS_MIN_FILE_EDITS", 2)

    rows = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        approve()

    # Anchor = the last index at which a distillation ALREADY happened, i.e.
    #   (a) a Task tool_use delegating to skill-distiller, or
    #   (b) a Write/Edit/MultiEdit whose file_path is a ~/.claude/skills SKILL.md.
    # Everything after the anchor is "work not yet distilled".
    anchor = -1
    for i, row in enumerate(rows):
        for tu in _tool_uses(row):
            name = tu.get("name")
            raw_inp = tu.get("input")
            inp = raw_inp if isinstance(raw_inp, dict) else {}
            if name == "Task":
                if SKILL_MARKER in json.dumps(inp, ensure_ascii=False):
                    anchor = i
            elif name in EDIT_TOOLS:
                if _is_skill_path(inp.get("file_path")):
                    anchor = i

    # Count tool calls and real file edits since the anchor.
    total_calls = 0
    file_edits = 0
    for row in rows[anchor + 1:]:
        for tu in _tool_uses(row):
            total_calls += 1
            if tu.get("name") in EDIT_TOOLS:
                file_edits += 1

    # Nudge only when the undistilled segment is BOTH substantial (enough tool
    # calls) AND has produced real artifacts (enough file edits). This keeps
    # pure exploration/Q&A turns from triggering, while staying broad across all
    # kinds of work (unlike dev-log's compiled-build-only trigger).
    if total_calls >= threshold and file_edits >= min_edits:
        reason = (
            "이번 작업 구간에서 도구 호출이 {calls}회(파일 편집 {edits}회) 누적됐고 "
            "아직 스킬로 증류되지 않았습니다. 종료하기 전에 Task 도구로 "
            'subagent_type="skill-distiller" 를 호출해, 이 세션에서 얻은 재사용 가능한 '
            "기법·패턴·해결책을 ~/.claude/skills 의 SKILL.md 로 캡처하세요.\n\n"
            "원칙:\n"
            "- 이미 관련된 기존 스킬이 있으면 새로 만들지 말고 그 SKILL.md 를 patch 하세요.\n"
            "- 한 번 쓰고 버릴 일회성 작업(특정 PR·특정 버그·환경 의존적 우회)이라면 "
            "캡처하지 말고 그대로 종료하세요.\n"
            "- 증류가 불필요하다고 판단되면, 그 이유를 사용자에게 한 줄로 알린 뒤 종료하세요."
        ).format(calls=total_calls, edits=file_edits)
        emit({"decision": "block", "reason": reason})

    approve()


if __name__ == "__main__":
    main()
