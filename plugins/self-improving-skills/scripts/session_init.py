#!/usr/bin/env python3
"""SessionStart-hook logic for the self-improving-skills plugin.

Injects a small amount of additionalContext at session start so the agent:
  1. knows the self-improvement loop is active and how to feed it (the advisory
     nudge — Hermes' SKILLS_GUIDANCE analogue),
  2. is aware of how many learned skills already exist under ~/.claude/skills, and
  3. is reminded to run /curate-skills when the learned-skill library has grown
     and hasn't been consolidated in a while (the Hermes 7-day curator analogue,
     here event-gated rather than wall-clock).

Output contract: a SessionStart hook adds context by printing
  {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}
to stdout. Fails safe to silent (no context) on any error.

Config:
  SIS_CURATE_MIN_SKILLS  learned-skill count above which curation is suggested (default 8)
  SIS_CURATE_INTERVAL_DAYS  days since last curation before re-suggesting (default 7)
"""

import json
import os
import sys
import time
from typing import NoReturn

SKILLS_DIR = os.path.expanduser("~/.claude/skills")
STATE_DIR = os.path.expanduser("~/.claude/self-improve")
CURATOR_STATE = os.path.join(STATE_DIR, "curator_state.json")
PROVENANCE_KEY = "self-improving-skills"  # marker we write into learned SKILL.md frontmatter


def emit_context(text) -> NoReturn:
    if text:
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": text,
            }
        }, ensure_ascii=False))
    sys.exit(0)


def _int_env(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _count_learned_skills():
    """Count SKILL.md files under ~/.claude/skills that this plugin distilled."""
    learned = 0
    if not os.path.isdir(SKILLS_DIR):
        return learned
    for root, dirs, files in os.walk(SKILLS_DIR):
        # don't descend into archives / vcs / caches
        dirs[:] = [d for d in dirs if d not in (".archive", ".git", "__pycache__", "node_modules")]
        if "SKILL.md" in files:
            try:
                with open(os.path.join(root, "SKILL.md"), encoding="utf-8", errors="ignore") as fh:
                    head = fh.read(2048)
                if PROVENANCE_KEY in head:
                    learned += 1
            except Exception:
                pass
    return learned


def _curation_due(learned_count):
    min_skills = _int_env("SIS_CURATE_MIN_SKILLS", 8)
    if learned_count < min_skills:
        return False
    interval = _int_env("SIS_CURATE_INTERVAL_DAYS", 7) * 86400
    try:
        with open(CURATOR_STATE, encoding="utf-8") as fh:
            last = float(json.load(fh).get("last_run", 0))
    except Exception:
        last = 0.0
    return (time.time() - last) >= interval


def main():
    try:
        sys.stdin.read()  # drain payload; we don't need its fields
    except Exception:
        pass

    try:
        learned = _count_learned_skills()
    except Exception:
        emit_context(None)

    lines = [
        "[self-improving-skills] 자기개선 루프가 활성화되어 있습니다.",
        "복잡한 작업·까다로운 디버깅·새로운 기법 발견을 끝낸 뒤, 그것이 재사용 가능하다면 "
        "Task 도구로 skill-distiller 서브에이전트를 호출하거나 /distill-skill 로 ~/.claude/skills 에 "
        "SKILL.md 를 만들어(또는 기존 스킬을 patch 하여) 다음 세션의 자신에게 남기세요. "
        "복잡한 구간을 그냥 종료하려 하면 Stop 훅이 한 번 상기시켜 줍니다.",
    ]
    if learned:
        lines.append("현재 학습된 스킬 {0}개가 ~/.claude/skills 에 누적되어 있습니다.".format(learned))

    try:
        if _curation_due(learned):
            lines.append(
                "학습된 스킬이 충분히 쌓였고 한동안 정리되지 않았습니다. "
                "여유가 있을 때 /curate-skills 로 중복 스킬을 통합하고 오래된 스킬을 아카이브하세요."
            )
    except Exception:
        pass

    emit_context("\n".join(lines))


if __name__ == "__main__":
    main()
