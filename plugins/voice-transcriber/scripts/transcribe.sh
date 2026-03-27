#!/bin/bash
set -euo pipefail

# Usage: transcribe.sh <audio_file>
# Output: 전사된 텍스트 (stdout)
# 오류: stderr로 출력, exit 1

if [ $# -eq 0 ]; then
  echo "ERROR: 오디오 파일 경로가 지정되지 않았습니다." >&2
  echo "Usage: transcribe.sh <audio_file>" >&2
  exit 1
fi

AUDIO_PATH="$1"

if [ ! -f "$AUDIO_PATH" ]; then
  echo "ERROR: 파일을 찾을 수 없습니다: $AUDIO_PATH" >&2
  exit 1
fi

# mlx-qwen3-asr 경로 탐색
MLX_ASR_BIN="${MLX_ASR_BIN:-}"
if [ -z "$MLX_ASR_BIN" ]; then
  MLX_ASR_BIN=$(command -v mlx-qwen3-asr 2>/dev/null || echo "")
  if [ -z "$MLX_ASR_BIN" ]; then
    # venv 기본 경로
    MLX_ASR_BIN="$HOME/.venvs/voice-transcriber/bin/mlx-qwen3-asr"
  fi
fi

if [ ! -x "$MLX_ASR_BIN" ]; then
  echo "ERROR: mlx-qwen3-asr를 찾을 수 없습니다. 설치가 필요합니다:" >&2
  echo "  uv venv ~/.venvs/voice-transcriber" >&2
  echo "  source ~/.venvs/voice-transcriber/bin/activate" >&2
  echo "  uv pip install mlx-qwen3-asr" >&2
  exit 1
fi

# Qwen3-ASR-1.7B로 전사 (가장 높은 정확도)
# --stdout-only: 파일 출력 없이 stdout으로만 전사 텍스트 출력
# --no-progress: 프로그레스 바 비활성화
"$MLX_ASR_BIN" \
  --model Qwen/Qwen3-ASR-1.7B \
  --dtype bfloat16 \
  --stdout-only \
  --no-progress \
  "$AUDIO_PATH"
