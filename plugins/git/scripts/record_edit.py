#!/usr/bin/env python3
"""PostToolUse hook: 이번 세션이 Edit/Write한 파일 경로를 repo별 세션 원장에 기록.

Claude가 Write/Edit/MultiEdit/NotebookEdit 도구를 호출할 때마다 실행된다.
stdin JSON에서 session_id와 수정 파일 경로(tool_input.file_path)를 읽어,
그 파일이 속한 git repo의 <git-common-dir>/claude-git-plugin/ 아래
  - edits-<session_id>.lst : 수정 파일 절대경로 (줄 단위 append, 중복 허용)
  - current-session        : 현재 활성 세션 id (마커 — 슬래시 명령어가 읽음)
를 갱신한다.

git repo 밖이거나 입력이 불완전하면 조용히 no-op.
hook이 사용자 작업을 절대 막지 않도록 모든 예외를 삼키고 항상 exit 0.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys


def _git_common_dir(path: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", path, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    gitdir = out.stdout.strip()
    if not gitdir:
        return None
    # rev-parse는 상대경로를 줄 수 있으므로 path 기준으로 절대경로화한다.
    if not os.path.isabs(gitdir):
        gitdir = os.path.normpath(os.path.join(path, gitdir))
    return gitdir


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0

    sid = payload.get("session_id")
    tool_input = payload.get("tool_input")
    fp = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not sid or not fp:
        return 0

    # 파일명에 안전한 형태로만 (session_id는 보통 UUID 형태).
    safe_sid = re.sub(r"[^A-Za-z0-9_-]", "", str(sid))
    if not safe_sid:
        return 0

    abs_fp = os.path.abspath(str(fp))
    target_dir = os.path.dirname(abs_fp) or "."
    if not os.path.isdir(target_dir):
        return 0

    gitdir = _git_common_dir(target_dir)
    if not gitdir:
        return 0

    state = os.path.join(gitdir, "claude-git-plugin")
    try:
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, f"edits-{safe_sid}.lst"), "a", encoding="utf-8") as f:
            f.write(abs_fp + "\n")
        tmp = os.path.join(state, "current-session.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(safe_sid)
        os.replace(tmp, os.path.join(state, "current-session"))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
