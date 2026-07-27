---
allowed-tools: Bash(bash:*), Bash(git add:*), Bash(git status:*), Bash(git commit:*), Bash(git branch:*), Bash(git log:*)
description: Create a git commit
---

## Context

- 이번 세션이 수정한 파일: !`bash "${CLAUDE_PLUGIN_ROOT}/scripts/session_files.sh"`
- 위 파일들의 변경 내용: !`bash "${CLAUDE_PLUGIN_ROOT}/scripts/session_files.sh" diff`
- 현재 브랜치: !`git branch --show-current`
- 최근 커밋: !`git log --oneline -10`

## Your task

위 "이번 세션이 수정한 파일" 목록을 기반으로 단일 git 커밋을 만든다.

규칙:

1. **그 목록의 파일만** `git add <path>`로 stage 한다. 작업트리의 다른 변경(사용자가 직접
   수정한 파일, 이번 세션과 무관한 기존 변경)은 **절대 stage 하지 않는다.** 목록의 각 경로를
   명시적으로 `git add` 한다 — `git add -A` / `git add .` / `git add -u` 는 쓰지 않는다.
2. 목록이 비어 있으면(이번 세션에 수정한 파일이 없음) 커밋하지 말고 그 사실만 한 줄로 보고하고
   종료한다.
3. 커밋 메시지는 한국어 conventional commit 형식: `<type>(<scope>): <요약>`
   (type = feat/fix/chore/docs/refactor 등, scope = 영향 플러그인/디렉터리명). 플러그인 버전을
   올렸다면 요약 끝에 `(vX.Y.Z)`를 덧붙인다.
4. 커밋 메시지에 co-author/trailer(`Co-Authored-By:` 등)를 **넣지 않는다.**
5. stage한 파일에 `**/.claude-plugin/plugin.json` 또는 `.claude-plugin/marketplace.json`이
   포함되면, 두 파일의 `version`이 같은 값으로 함께 bump되었는지 확인한다(어긋나면 커밋 전에 맞춘다).

You have the capability to call multiple tools in a single response. Stage and create the commit using a single message.
Do not do anything else. Do not send any other text or messages besides these tool calls (목록이 비어 보고하는 경우는 예외).
