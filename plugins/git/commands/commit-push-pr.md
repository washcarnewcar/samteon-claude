---
allowed-tools: Bash(bash:*), Bash(git checkout:*), Bash(git add:*), Bash(git status:*), Bash(git push:*), Bash(git commit:*), Bash(git branch:*), Bash(git log:*), Bash(gh pr create:*)
description: Commit, push, and open a PR
---

## Context

- 이번 세션이 수정한 파일: !`bash "${CLAUDE_PLUGIN_ROOT}/scripts/session_files.sh"`
- 위 파일들의 변경 내용: !`bash "${CLAUDE_PLUGIN_ROOT}/scripts/session_files.sh" diff`
- 현재 브랜치: !`git branch --show-current`

## Your task

위 "이번 세션이 수정한 파일" 목록을 기반으로:

1. main 브랜치이면 새 브랜치를 만든다 (`git checkout -b <branch>`).
2. 그 목록의 파일만 stage 하여 단일 커밋을 만든다.
3. 브랜치를 origin에 push 한다.
4. `gh pr create`로 pull request를 만든다.

규칙:

1. **그 목록의 파일만** `git add <path>`로 stage 한다. 작업트리의 다른 변경은 **절대 stage 하지
   않는다.** 각 경로를 명시적으로 `git add` 하며 `git add -A` / `git add .` / `git add -u` 는
   쓰지 않는다.
2. 목록이 비어 있으면 아무 작업도 하지 말고 그 사실만 한 줄로 보고하고 종료한다.
3. 커밋 메시지는 한국어 conventional commit `<type>(<scope>): <요약>` (버전 bump 시 `(vX.Y.Z)`).
   커밋 메시지에 co-author/trailer를 **넣지 않는다.**
4. stage한 파일에 `**/.claude-plugin/plugin.json` 또는 `.claude-plugin/marketplace.json`이
   포함되면, 두 파일의 `version`이 같은 값으로 함께 bump되었는지 확인한다.

You have the capability to call multiple tools in a single response. You MUST do all of the above in a single
message. Do not do anything else. Do not send any other text or messages besides these tool calls (목록이 비어
보고하는 경우는 예외).
