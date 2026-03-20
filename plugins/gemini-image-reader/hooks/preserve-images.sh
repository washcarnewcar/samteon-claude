#!/bin/bash
set -euo pipefail

# 현재 디렉토리와 일치하는 세션 UUID 찾기
SESSION_UUID=""
for f in ~/.claude/sessions/*.json; do
  s_cwd=$(jq -r '.cwd' "$f" 2>/dev/null)
  if [ "$s_cwd" = "$PWD" ]; then
    SESSION_UUID=$(jq -r '.sessionId' "$f" 2>/dev/null)
  fi
done

if [ -z "$SESSION_UUID" ]; then
  exit 0
fi

# image-cache에 이미지가 있으면 /tmp/gemini_images/에 복사
SRC_DIR="$HOME/.claude/image-cache/$SESSION_UUID"
DST_DIR="/tmp/gemini_images/$SESSION_UUID"

if [ -d "$SRC_DIR" ]; then
  mkdir -p "$DST_DIR"
  for img in "$SRC_DIR"/*.png; do
    if [ -f "$img" ]; then
      base=$(basename "$img")
      if [ ! -f "$DST_DIR/$base" ]; then
        cp "$img" "$DST_DIR/$base"
      fi
    fi
  done
fi

exit 0
