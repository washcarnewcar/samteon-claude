#!/bin/bash
set -euo pipefail

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')

# 이미지 확장자 체크 (대소문자 무시, Bash 3.2 호환)
file_path_lower=$(echo "$file_path" | tr '[:upper:]' '[:lower:]')
if [[ "$file_path_lower" =~ \.(png|jpg|jpeg|gif|webp|bmp)$ ]]; then
  cat >&2 <<'EOF'
{"hookSpecificOutput": {"permissionDecision": "deny"}, "systemMessage": "BLOCKED: 이미지 파일을 Read 도구로 직접 읽을 수 없습니다. gemini-image-reader 스킬을 사용하세요. Skill tool -> skill: 'gemini-image-reader'. Claude의 자체 이미지 분석 대신 Gemini CLI를 통해 더 정확한 분석 결과를 얻을 수 있습니다."}
EOF
  exit 2
fi

exit 0
