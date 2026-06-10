---
allowed-tools: Bash(git fetch:*), Bash(git merge:*), Bash(git checkout:*), Bash(git switch:*), Bash(git pull:*), Bash(git push:*), Bash(git status:*), Bash(git branch:*), Bash(git log:*), Bash(git symbolic-ref:*), Bash(git rev-parse:*)
argument-hint: "[to-main]"
description: 현재 브랜치를 main과 동기화(기본)하거나, 현재 브랜치를 main에 머지(to-main)
---

## Context

- 현재 브랜치: !`git branch --show-current`
- 기본 브랜치: !`git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@' || echo main`
- 작업트리 상태: !`git status --short`
- 인자: $ARGUMENTS

## Your task

위 "기본 브랜치"(보통 `main`)를 기준으로, `$ARGUMENTS` 에 따라 두 방향 중 하나로 머지한다.

### 인자가 없으면 — sync (기본 브랜치 → 현재 브랜치)

현재 작업 브랜치에 기본 브랜치의 최신 변경을 가져온다.

1. `git fetch origin`
2. 현재 브랜치가 곧 기본 브랜치이면 `git merge --ff-only origin/<기본브랜치>` 로 최신화한다.
   그렇지 않으면 `git merge origin/<기본브랜치>` 로 현재 브랜치 위에 병합한다.
3. 충돌이 나면 더 진행하지 말고 멈춘 뒤, 충돌 파일 목록과 함께
   "충돌을 해결 후 커밋" / "`git merge --abort` 로 되돌리기" 두 선택지를 보고한다.

### 인자가 `to-main` 이면 — 현재 브랜치 → 기본 브랜치

현재 브랜치의 작업을 기본 브랜치에 병합하고 원격에 올린다.

1. 작업트리가 깨끗한지 확인한다(위 "작업트리 상태"가 비어 있어야 함). 변경이 남아 있으면 머지하지
   말고 "`/commit` 으로 먼저 커밋하라"고 보고하고 종료한다.
2. 현재 브랜치명을 기억한다(= `<feature>`). 이미 기본 브랜치 위라면 할 일이 없음을 보고하고 종료한다.
3. `git checkout <기본브랜치>` → `git pull --ff-only`
4. `git merge --no-ff <feature>`
5. 충돌이 나면 멈추고 충돌 파일과 "해결 후 커밋" / "`git merge --abort`" 선택지를 보고한다.
6. 머지가 성공하면 `git push` 로 기본 브랜치를 원격에 올린다.

You have the capability to call multiple tools in a single response. 필요한 git 명령을 호출해 위 절차를
수행하고, 결과(머지 완료 / 충돌 / 스킵)를 간결히 보고한다.
