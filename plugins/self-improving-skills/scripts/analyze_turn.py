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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import usage_store
except Exception:
    usage_store = None  # telemetry is best-effort; nudge logic works without it

SKILL_MARKER = "skill-distiller"
EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
SKILLS_DIR = os.path.expanduser("~/.claude/skills")


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


def _learned_skill_names():
    """Names of learned skills = immediate dirs under ~/.claude/skills with a SKILL.md."""
    names = set()
    try:
        for entry in os.listdir(SKILLS_DIR):
            if entry.startswith("."):
                continue
            if os.path.isfile(os.path.join(SKILLS_DIR, entry, "SKILL.md")):
                names.add(entry)
    except Exception:
        pass
    return names


def _skill_name_from_path(file_path):
    """The skill name for a ~/.claude/skills/<name>/SKILL.md path (dir basename)."""
    if not _is_skill_path(file_path):
        return None
    norm = str(file_path).replace("\\", "/")
    return os.path.basename(os.path.dirname(norm)) or None


def _capture_telemetry(rows, session_id):
    """Best-effort: bump use/view/patch counters for learned skills from new
    transcript rows (since this session's last processed offset). Signals
    (verified against real transcripts):
      - Skill tool, input.skill (namespace-stripped) matches a learned skill -> use
      - Read of a ~/.claude/skills/**/SKILL.md                                -> view
      - Write/Edit/MultiEdit of the same                                      -> patch
    """
    if usage_store is None:
        return
    learned = _learned_skill_names()
    try:
        usage_store.forget_missing(learned)
    except Exception:
        pass

    offset = 0
    try:
        offset = usage_store.get_offset(session_id)
    except Exception:
        offset = 0
    if offset < 0 or offset > len(rows):
        offset = 0

    events = []
    if learned:
        for row in rows[offset:]:
            for tu in _tool_uses(row):
                name = tu.get("name")
                raw_inp = tu.get("input")
                inp = raw_inp if isinstance(raw_inp, dict) else {}
                if name == "Skill":
                    sk = str(inp.get("skill", "")).split(":")[-1]
                    if sk in learned:
                        events.append((sk, "use", "agent"))
                elif name == "Read":
                    sn = _skill_name_from_path(inp.get("file_path"))
                    if sn in learned:
                        events.append((sn, "view", "agent"))
                elif name in EDIT_TOOLS:
                    sn = _skill_name_from_path(inp.get("file_path"))
                    if sn in learned:
                        events.append((sn, "patch", "agent"))
    try:
        usage_store.apply_events(events, session_id, len(rows))
    except Exception:
        pass


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

    # Telemetry capture (best-effort, isolated): record skill use/view/patch from
    # new transcript rows. Never let this affect the nudge decision below.
    try:
        session_id = str(payload.get("session_id") or os.path.basename(path))
        _capture_telemetry(rows, session_id)
    except Exception:
        pass

    # Anchor = the last index at which a distillation ALREADY happened, i.e.
    #   (a) a subagent delegation to skill-distiller, or
    #   (b) a Write/Edit/MultiEdit whose file_path is a ~/.claude/skills SKILL.md.
    # Everything after the anchor is "work not yet distilled".
    #
    # NOTE: the subagent-spawning tool is named differently across Claude Code
    # surfaces ("Task" in the docs, "Agent" in some runtimes), and the
    # subagent_type may carry a plugin namespace prefix
    # ("self-improving-skills:skill-distiller"). So we key on the *presence of a
    # subagent_type input* containing the distiller marker — environment- and
    # name-agnostic — rather than hardcoding the tool name. (Getting this wrong
    # is exactly the class of silent-mismatch bug dev-log hit; verified against a
    # real transcript where the tool name was "Agent", not "Task".)
    anchor = -1
    for i, row in enumerate(rows):
        for tu in _tool_uses(row):
            name = tu.get("name")
            raw_inp = tu.get("input")
            inp = raw_inp if isinstance(raw_inp, dict) else {}
            subagent_type = str(inp.get("subagent_type", ""))
            if SKILL_MARKER in subagent_type:
                anchor = i
            elif name in EDIT_TOOLS and _is_skill_path(inp.get("file_path")):
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
            "아직 스킬로 증류되지 않았습니다. 종료하기 전에 /distill-skill 을 실행하거나 "
            'skill-distiller 서브에이전트(subagent_type="skill-distiller")를 호출해, '
            "이 세션에서 얻은 재사용 가능한 기법·패턴·해결책을 ~/.claude/skills 의 "
            "SKILL.md 로 캡처하세요.\n\n"
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
