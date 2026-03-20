#!/bin/bash
set -euo pipefail

# Usage: gemini-analyze.sh "<prompt>" [image_path...]
# - image_path 없으면 → image-cache에서 가장 최근 이미지 자동 탐색
# - image_path가 상대 경로면 → 절대 경로로 변환
# - 여러 이미지 지원

# #2: 인자 검증
if [ $# -eq 0 ]; then
  echo "ERROR: 프롬프트가 지정되지 않았습니다." >&2
  echo "Usage: gemini-analyze.sh \"<prompt>\" [image_path...]" >&2
  exit 1
fi

PROMPT="$1"
shift

# #6: Gemini CLI 경로 동적 탐색
GEMINI_BIN=$(command -v gemini 2>/dev/null || echo "/opt/homebrew/bin/gemini")

# #7: 중복 방지 디렉토리 추가 함수 (Bash 3.2 호환)
add_include_dir() {
  local new_dir="$1"
  for existing in "${INCLUDE_DIRS[@]}"; do
    if [ "$existing" = "$new_dir" ]; then
      return
    fi
  done
  INCLUDE_DIRS+=("$new_dir")
}

# 이미지 경로 수집
IMAGE_REFS=""
INCLUDE_DIRS=("$HOME/.claude/image-cache" "$PWD")

if [ $# -eq 0 ]; then
  # #5: 인자 없으면 image-cache에서 가장 최근 이미지 찾기 (지원 형식 확장)
  IMAGE_PATH=$(find ~/.claude/image-cache \
    \( -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" -o -name "*.webp" -o -name "*.gif" -o -name "*.bmp" \) \
    -type f -exec stat -f '%m %N' {} \; 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
  # #1: cut -d' ' -f2- 로 공백 포함 경로 안전 처리
  if [ -z "$IMAGE_PATH" ]; then
    echo "ERROR: image-cache에 이미지가 없습니다. 이미지 파일 경로를 직접 지정해주세요." >&2
    exit 1
  fi
  IMAGE_REFS="@$IMAGE_PATH"
  add_include_dir "$(dirname "$IMAGE_PATH")"
else
  # 인자로 받은 경로를 절대 경로로 변환
  for path in "$@"; do
    abs_path=$(cd "$(dirname "$path")" 2>/dev/null && pwd)/$(basename "$path")
    if [ ! -f "$abs_path" ]; then
      echo "ERROR: 파일을 찾을 수 없습니다: $path" >&2
      exit 1
    fi
    # #4: 선행 공백 없이 조합
    if [ -z "$IMAGE_REFS" ]; then
      IMAGE_REFS="@$abs_path"
    else
      IMAGE_REFS="$IMAGE_REFS @$abs_path"
    fi
    add_include_dir "$(dirname "$abs_path")"
  done
fi

# Gemini CLI 호출 (--include-directories에 이미지 디렉토리 포함, 존재하는 디렉토리만)
INCLUDE_ARGS=()
for dir in "${INCLUDE_DIRS[@]}"; do
  if [ -d "$dir" ]; then
    INCLUDE_ARGS+=("--include-directories" "$dir")
  fi
done

FULL_PROMPT="$PROMPT $IMAGE_REFS"
# #3: stderr 억제 제거
"$GEMINI_BIN" \
  "${INCLUDE_ARGS[@]}" \
  -p "$FULL_PROMPT" \
  --yolo
