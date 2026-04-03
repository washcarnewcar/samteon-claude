#!/bin/bash
set -euo pipefail

input=$(cat)
transcript_path=$(echo "$input" | jq -r '.transcript_path // empty')

# 변경된 코드 파일 확인 (staged + unstaged)
code_extensions="ts|tsx|js|jsx|py|swift|kt|java|go|rs|c|cpp|h|css|scss|html|vue|svelte|rb|php|sh|sql"
changed_code_files=$(git diff --name-only HEAD 2>/dev/null | grep -iE "\.($code_extensions)$" || true)
unstaged_code_files=$(git diff --name-only 2>/dev/null | grep -iE "\.($code_extensions)$" || true)
all_code_files="$changed_code_files$unstaged_code_files"

if [ -z "$all_code_files" ]; then
  echo '{"decision": "approve"}'
  exit 0
fi

# transcript에서 feature 스킬 실제 호출 흔적 확인
# Skill 도구 호출 패턴: "skill": "feature:test-writing" 또는 "skill": "feature:code-review"
if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
  if grep -qE '"skill".*"feature:(test-writing|code-review)"' "$transcript_path" 2>/dev/null; then
    echo '{"decision": "approve"}'
    exit 0
  fi
  # 폴백: Agent로 test-writer/code-reviewer를 호출한 경우도 허용
  if grep -qE '"subagent_type".*"(feature:test-writer|feature:code-reviewer|test-writer|code-reviewer)"' "$transcript_path" 2>/dev/null; then
    echo '{"decision": "approve"}'
    exit 0
  fi
fi

# 코드 변경 있는데 feature 스킬 미사용 → 종료 차단
echo '{"decision": "block", "reason": "코드 파일이 수정되었지만 feature 스킬이 실행되지 않았습니다.", "systemMessage": "BLOCKED: 코드 파일이 수정되었습니다. 종료하기 전에 반드시 feature 스킬을 실행하세요.\n\n1. Skill tool -> skill: '\''feature:test-writing'\'' (테스트 작성)\n2. Skill tool -> skill: '\''feature:code-review'\'' (코드 리뷰)\n\n사용자가 '\''테스트 건너뛰어'\'' 또는 '\''리뷰 건너뛰어'\''라고 명시적으로 말한 경우에만 생략할 수 있습니다."}'
exit 2
