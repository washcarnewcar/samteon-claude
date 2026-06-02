#!/usr/bin/env python3
"""PostToolUse-hook logic for the self-improving-skills plugin.

Runs after every Write/Edit/MultiEdit. It only acts when the edited file is a
SKILL.md under ~/.claude/skills (a learned skill); for everything else it stays
silent. For a learned skill it:

  1. Validates the on-disk SKILL.md against the Claude Code skill contract:
       - starts with a `---` frontmatter block that closes with `---`
       - frontmatter has a non-empty `name` (<=64 chars, lowercase/digits/hyphen)
       - frontmatter has a non-empty `description` (<=1024 chars)
       - non-empty body after the frontmatter
       - whole file <= 100000 chars
     and surfaces any problems back to the agent as additionalContext so it can
     fix them immediately.
  2. Stamps provenance: if the frontmatter has no `metadata:` provenance marker,
     it injects one (`metadata: { provenance: self-improving-skills, ... }`) so
     /curate-skills and the SessionStart counter can later tell agent-distilled
     skills apart from user-authored ones. Stamping never overwrites existing
     metadata and is skipped if it can't be done cleanly.

Output contract: print a PostToolUse JSON object with
`hookSpecificOutput.additionalContext` when there's something to say; otherwise
print nothing. Fails safe to silent on any error — validation feedback must
never break the edit that already happened.
"""

import json
import os
import re
import sys
from typing import NoReturn

MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_CONTENT = 100000
PROVENANCE_VALUE = "self-improving-skills"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def silent() -> NoReturn:
    sys.exit(0)


def feedback(text) -> NoReturn:
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": text,
        }
    }, ensure_ascii=False))
    sys.exit(0)


def _is_learned_skill(file_path):
    norm = str(file_path or "").replace("\\", "/")
    return "/.claude/skills/" in norm and norm.endswith("SKILL.md")


def _split_frontmatter(text):
    """Return (frontmatter_str, body_str) or (None, None) if malformed."""
    if not text.startswith("---"):
        return None, None
    # find the closing '---' on its own line after the first
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _scalar(frontmatter, key):
    """Cheap YAML scalar read for top-level `key: value` (quoted or bare)."""
    for line in frontmatter.splitlines():
        m = re.match(r"^" + re.escape(key) + r"\s*:\s*(.*)$", line)
        if m:
            val = m.group(1).strip()
            if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
                val = val[1:-1]
            return val
    return None


def _validate(text):
    problems = []
    if len(text) > MAX_CONTENT:
        problems.append("파일이 너무 큽니다(>{0}자). references/ 로 본문을 분리하세요.".format(MAX_CONTENT))

    fm, body = _split_frontmatter(text)
    if fm is None:
        problems.append("YAML frontmatter 가 없습니다. 파일은 `---` 로 시작하고 `---` 로 닫혀야 합니다.")
        return problems

    name = _scalar(fm, "name")
    if not name:
        problems.append("frontmatter 에 `name` 이 없습니다.")
    else:
        if len(name) > MAX_NAME:
            problems.append("`name` 이 {0}자를 초과합니다.".format(MAX_NAME))
        if not NAME_RE.match(name):
            problems.append("`name` 은 소문자·숫자·하이픈만 사용해야 합니다(예: my-skill-name).")

    desc = _scalar(fm, "description")
    if not desc:
        problems.append("frontmatter 에 `description` 이 없습니다. 트리거 정확도의 핵심이니 "
                        "'이럴 때 사용한다'는 상황 중심으로 한 문장 작성하세요.")
    elif len(desc) > MAX_DESCRIPTION:
        problems.append("`description` 이 {0}자를 초과합니다.".format(MAX_DESCRIPTION))

    if not body or not body.strip():
        problems.append("frontmatter 뒤 본문(스킬 지침)이 비어 있습니다.")

    return problems


def _stamp_provenance(path, text):
    """Inject a provenance metadata marker if none exists. Best-effort."""
    if PROVENANCE_VALUE in text:
        return  # already stamped (or mentioned) — don't touch
    fm, body = _split_frontmatter(text)
    if fm is None or body is None:
        return
    if re.search(r"^metadata\s*:", fm, re.MULTILINE):
        return  # author already manages metadata; leave it alone
    new_fm = fm.rstrip("\n") + (
        "\nmetadata:\n"
        "  provenance: {0}\n".format(PROVENANCE_VALUE)
    )
    new_text = "---\n" + new_fm + "\n---\n" + body
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
    except Exception:
        pass


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        silent()

    raw_input = payload.get("tool_input")
    tool_input = raw_input if isinstance(raw_input, dict) else {}
    file_path = tool_input.get("file_path", "")
    if not _is_learned_skill(file_path) or not os.path.isfile(file_path):
        silent()

    try:
        with open(file_path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except Exception:
        silent()

    problems = _validate(text)
    if not problems:
        _stamp_provenance(file_path, text)
        silent()

    msg = (
        "[self-improving-skills] 방금 작성한 학습 스킬 {0} 에 문제가 있습니다:\n- ".format(file_path)
        + "\n- ".join(problems)
        + "\n수정한 뒤 다시 저장하세요."
    )
    feedback(msg)


if __name__ == "__main__":
    main()
