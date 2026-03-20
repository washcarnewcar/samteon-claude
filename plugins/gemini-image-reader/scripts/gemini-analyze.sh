#!/bin/bash
set -euo pipefail

# Usage: gemini-analyze.sh "<prompt>" [image_path...]
# - image_path 없으면 → image-cache에서 가장 최근 이미지 자동 탐색
# - image_path가 상대 경로면 → 절대 경로로 변환
# - 여러 이미지 지원

PROMPT="$1"
shift

# 이미지 경로 수집
IMAGE_REFS=""

if [ $# -eq 0 ]; then
  # 인자 없으면 image-cache에서 가장 최근 이미지 찾기
  IMAGE_PATH=$(find ~/.claude/image-cache -name "*.png" -type f \
    -exec stat -f '%m %N' {} \; 2>/dev/null | sort -rn | head -1 | awk '{print $2}')
  if [ -z "$IMAGE_PATH" ]; then
    echo "ERROR: image-cache에 이미지가 없습니다. 이미지 파일 경로를 직접 지정해주세요." >&2
    exit 1
  fi
  IMAGE_REFS="@$IMAGE_PATH"
else
  # 인자로 받은 경로를 절대 경로로 변환
  for path in "$@"; do
    abs_path=$(cd "$(dirname "$path")" 2>/dev/null && pwd)/$(basename "$path")
    if [ ! -f "$abs_path" ]; then
      echo "ERROR: 파일을 찾을 수 없습니다: $path" >&2
      exit 1
    fi
    IMAGE_REFS="$IMAGE_REFS @$abs_path"
  done
fi

# Gemini CLI 호출
FULL_PROMPT="$PROMPT $IMAGE_REFS"
/opt/homebrew/bin/gemini \
  --include-directories "$HOME/.claude/image-cache" \
  --include-directories /tmp \
  --include-directories "$PWD" \
  -p "$FULL_PROMPT" \
  --yolo \
  2>/dev/null
