#!/usr/bin/env bash
# 이번 세션이 수정했고 아직 커밋되지 않은 파일을 다룬다.
#
# 사용법:
#   session_files.sh        세션 수정 파일을 repo 루트 기준 상대경로로 한 줄씩 출력
#   session_files.sh diff   위 파일들의 `git diff HEAD` 출력
#
# 원장(<git-common-dir>/claude-git-plugin/edits-<sid>.lst)과
# 실제 변경(git status)의 교집합만 다룬다. 커밋 계열 슬래시 명령어가
# Context 섹션에서 `!` 로 주입해 사용한다. 세션 수정 파일이 없으면 빈 출력.
set -euo pipefail

gitdir=$(git rev-parse --git-common-dir 2>/dev/null) || exit 0
case "$gitdir" in
  /*) : ;;
  *)  gitdir="$(pwd)/$gitdir" ;;
esac

state="$gitdir/claude-git-plugin"
marker="$state/current-session"
[ -f "$marker" ] || exit 0
sid=$(cat "$marker" 2>/dev/null) || exit 0
[ -n "$sid" ] || exit 0
ledger="$state/edits-$sid.lst"
[ -f "$ledger" ] || exit 0

root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0

# 원장 ∩ (실제 변경된 파일). 원장 경로 각각에 대해 개별 git status로 확인하여
# 공백 포함 경로에도 안전하게 처리한다.
files=$(sort -u "$ledger" | while IFS= read -r abs; do
  [ -n "$abs" ] || continue
  rel=${abs#"$root/"}
  [ "$rel" != "$abs" ] || continue   # repo 루트 밖의 경로는 제외
  if [ -n "$(git status --porcelain --untracked-files=all -- "$abs" 2>/dev/null)" ]; then
    printf '%s\n' "$rel"
  fi
done)

[ -n "$files" ] || exit 0

if [ "${1:-}" = "diff" ]; then
  printf '%s\n' "$files" | (cd "$root" && tr '\n' '\0' | xargs -0 git --no-pager diff HEAD --)
else
  printf '%s\n' "$files"
fi
