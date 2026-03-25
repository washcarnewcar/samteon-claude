#!/bin/bash
set -euo pipefail

input=$(cat)
transcript_path=$(echo "$input" | jq -r '.transcript_path // empty')

if [ -z "$transcript_path" ] || [ ! -f "$transcript_path" ]; then
  echo '{"decision": "approve"}'
  exit 0
fi

# 실제 코드 편집이 있었는지 확인 (Edit/Write tool 사용 흔적)
has_code_edit=$(grep -cE '"tool":\s*"(Edit|Write)"' "$transcript_path" 2>/dev/null) || has_code_edit=0
if [ "$has_code_edit" -lt 1 ]; then
  echo '{"decision": "approve"}'
  exit 0
fi

# transcript에서 빌드 에러/수정 관련 키워드 확인
has_error_fix=$(grep -ciE "(build (failed|error|succeeded)|compile error|type.?check|runtime crash|deprecat|빌드 (에러|오류|성공)|컴파일|워닝 해결|경고 해결|에러 수정|버그 수정|breaking change)" "$transcript_path" 2>/dev/null) || has_error_fix=0

if [ "$has_error_fix" -lt 5 ]; then
  echo '{"decision": "approve"}'
  exit 0
fi

# dev-log 스킬 사용 흔적 확인
if grep -q "dev-log" "$transcript_path" 2>/dev/null; then
  echo '{"decision": "approve"}'
  exit 0
fi

# 에러 수정 흔적은 있는데 dev-log 미사용 → 종료 차단
cat >&2 <<'EOF'
{"decision": "block", "reason": "빌드 에러/경고 수정 흔적이 있지만 dev-log가 작성되지 않았습니다.", "systemMessage": "BLOCKED: 이 세션에서 빌드 에러나 경고를 수정한 것으로 보입니다. 종료하기 전에 dev-log 스킬을 실행하여 해결 과정을 기록하세요.\n\nSkill tool -> skill: 'dev-log'\n\n사용자가 'dev-log 건너뛰어'라고 명시적으로 말한 경우에만 생략할 수 있습니다."}
EOF
exit 2
