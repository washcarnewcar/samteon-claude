#!/usr/bin/env python3
"""SessionStart hook: repo의 오래된 세션 원장 파일을 정리(선택적 위생).

정확성에는 무관하다 — current-session 마커와 세션별 원장 파일명(edits-<sid>.lst)으로
세션이 격리되므로, 지난 세션의 원장은 단순 잔여물일 뿐이다. 7일 지난 것만 제거한다.
모든 예외를 삼키고 항상 exit 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

MAX_AGE_SECONDS = 7 * 24 * 3600


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    cwd = None
    if isinstance(payload, dict):
        cwd = payload.get("cwd")
    cwd = cwd or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return 0
    if out.returncode != 0:
        return 0
    gitdir = out.stdout.strip()
    if not gitdir:
        return 0
    if not os.path.isabs(gitdir):
        gitdir = os.path.normpath(os.path.join(cwd, gitdir))

    state = os.path.join(gitdir, "claude-git-plugin")
    if not os.path.isdir(state):
        return 0

    now = time.time()
    try:
        for name in os.listdir(state):
            if not (name.startswith("edits-") and name.endswith(".lst")):
                continue
            path = os.path.join(state, name)
            try:
                if now - os.path.getmtime(path) > MAX_AGE_SECONDS:
                    os.remove(path)
            except Exception:
                continue
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
