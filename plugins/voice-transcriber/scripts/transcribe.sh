#!/bin/bash
set -euo pipefail
trap 'kill 0 2>/dev/null' TERM INT

# Usage:
#   transcribe.sh <audio_file>                                        # 일반 전사 (한국어, stdout 텍스트)
#   transcribe.sh --language English <audio_file>                     # 영어 전사
#   transcribe.sh --diarize <audio_file>                              # 화자구분 전사 (자동 감지)
#   transcribe.sh --diarize --num-speakers <N> <audio_file>           # 화자구분 전사 (화자 수 지정)
#   transcribe.sh --diarize --output <dir> <audio_file>               # 출력 디렉토리 지정
#
# asr_mode 설정 (.claude/voice-transcriber.local.md):
#   server — 상주 서버 사용 (5분 유휴 시 모델 자동 언로드)
#   cli    — 매번 CLI 실행 (기본값)

DIARIZE=false
OUTPUT_DIR=""
NUM_SPEAKERS=""
LANGUAGE="Korean"
AUDIO_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --diarize)
      DIARIZE=true
      shift
      ;;
    --output)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --output 옵션에 디렉토리 경로가 필요합니다." >&2
        exit 1
      fi
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --num-speakers)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --num-speakers 옵션에 숫자가 필요합니다." >&2
        exit 1
      fi
      NUM_SPEAKERS="$2"
      shift 2
      ;;
    --language)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --language 옵션에 언어명이 필요합니다." >&2
        exit 1
      fi
      LANGUAGE="$2"
      shift 2
      ;;
    -*)
      echo "ERROR: 알 수 없는 옵션: $1" >&2
      exit 1
      ;;
    *)
      AUDIO_PATH="$1"
      shift
      ;;
  esac
done

if [ -z "$AUDIO_PATH" ]; then
  echo "ERROR: 오디오 파일 경로가 지정되지 않았습니다." >&2
  echo "Usage: transcribe.sh [--diarize] [--output <dir>] <audio_file>" >&2
  exit 1
fi

if [ ! -f "$AUDIO_PATH" ]; then
  echo "ERROR: 파일을 찾을 수 없습니다: $AUDIO_PATH" >&2
  exit 1
fi

if [ "$DIARIZE" = false ] && [ -n "$OUTPUT_DIR" ]; then
  echo "ERROR: --output 옵션은 --diarize와 함께 사용해야 합니다." >&2
  exit 1
fi

if [ "$DIARIZE" = false ] && [ -n "$NUM_SPEAKERS" ]; then
  echo "ERROR: --num-speakers 옵션은 --diarize와 함께 사용해야 합니다." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$HOME/.venvs/voice-transcriber/bin/python}"

# --- 설정 읽기 ---
ASR_MODE="cli"
LOCAL_MD=".claude/voice-transcriber.local.md"
if [ -f "$LOCAL_MD" ]; then
  MODE_VAL=$(sed -n '/^---$/,/^---$/{ /^---$/d; p; }' "$LOCAL_MD" | grep '^asr_mode:' | sed 's/asr_mode: *//' | sed 's/^"\(.*\)"$/\1/' || true)
  if [ -n "$MODE_VAL" ]; then
    ASR_MODE="$MODE_VAL"
  fi
fi

# ============================================================
#  SERVER 모드
# ============================================================
if [ "$ASR_MODE" = "server" ]; then
  ASR_PORT="${ASR_PORT:-8787}"
  ASR_URL="http://127.0.0.1:${ASR_PORT}"

  # 서버 생존 확인, 없으면 시작
  if ! curl -sf "${ASR_URL}/health" >/dev/null 2>&1; then
    echo "[transcribe] ASR 서버 시작 중..." >&2
    nohup "$PYTHON_BIN" "$SCRIPT_DIR/asr-server.py" --port "$ASR_PORT" \
      >/tmp/asr-server.log 2>&1 &
    # 최대 60초 대기
    for i in $(seq 1 60); do
      if curl -sf "${ASR_URL}/health" >/dev/null 2>&1; then
        echo "[transcribe] ASR 서버 준비 완료 (${i}초)" >&2
        break
      fi
      if [ "$i" -eq 60 ]; then
        echo "ERROR: ASR 서버 시작 타임아웃 (60초). 로그: /tmp/asr-server.log" >&2
        exit 1
      fi
      sleep 1
    done
  fi

  # JSON body 구성
  JSON_BODY="{\"audio_path\":\"${AUDIO_PATH}\",\"language\":\"${LANGUAGE}\",\"diarize\":${DIARIZE}"
  if [ "$DIARIZE" = true ] && [ -n "$NUM_SPEAKERS" ]; then
    JSON_BODY="${JSON_BODY},\"num_speakers\":${NUM_SPEAKERS}"
  fi
  JSON_BODY="${JSON_BODY}}"

  # 전사 요청
  RESPONSE=$(curl -sf --max-time 600 -X POST "${ASR_URL}/transcribe" \
    -H "Content-Type: application/json" \
    -d "$JSON_BODY")

  # 에러 체크
  ERROR=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" 2>/dev/null || true)
  if [ -n "$ERROR" ]; then
    echo "ERROR: $ERROR" >&2
    exit 1
  fi

  if [ "$DIARIZE" = true ]; then
    # 화자구분: JSON → 파일 저장 → format-transcript.py
    if [ -z "$OUTPUT_DIR" ]; then
      OUTPUT_DIR=$(mktemp -d)
    fi
    mkdir -p "$OUTPUT_DIR"

    AUDIO_BASE=$(basename "$AUDIO_PATH")
    AUDIO_STEM="${AUDIO_BASE%.*}"
    JSON_PATH="$OUTPUT_DIR/${AUDIO_STEM}.json"

    # 서버 응답에서 speaker_segments → segments로 변환하여 저장
    echo "$RESPONSE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
out = {'text': d.get('text', ''), 'segments': d.get('speaker_segments', [])}
json.dump(out, sys.stdout, ensure_ascii=False)
" > "$JSON_PATH"

    "$PYTHON_BIN" "$SCRIPT_DIR/format-transcript.py" "$JSON_PATH"
  else
    # 일반 전사: text 추출 → stdout
    echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('text',''))"
  fi

  exit 0
fi

# ============================================================
#  CLI 모드 (기본값)
# ============================================================

# mlx-qwen3-asr 경로 탐색
MLX_ASR_BIN="${MLX_ASR_BIN:-}"
if [ -z "$MLX_ASR_BIN" ]; then
  MLX_ASR_BIN=$(command -v mlx-qwen3-asr 2>/dev/null || echo "")
  if [ -z "$MLX_ASR_BIN" ]; then
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

# 공통 인자
MODEL="Qwen/Qwen3-ASR-1.7B"
DTYPE="bfloat16"
COMMON_ARGS=(--model "$MODEL" --dtype "$DTYPE" --language "$LANGUAGE" --no-progress)

if [ "$DIARIZE" = true ]; then
  # diarize extras 설치 여부 사전 검사
  DOCTOR_OUTPUT=$("$MLX_ASR_BIN" --doctor 2>&1 || true)
  if echo "$DOCTOR_OUTPUT" | grep -q "diarize extras: missing"; then
    echo "ERROR: 화자 분리(diarize) 기능에 추가 패키지 설치가 필요합니다:" >&2
    echo "  $HOME/.venvs/voice-transcriber/bin/python -m pip install \"mlx-qwen3-asr[diarize]\"" >&2
    exit 1
  fi

  # 출력 디렉토리 결정
  if [ -z "$OUTPUT_DIR" ]; then
    OUTPUT_DIR=$(mktemp -d)
  fi
  mkdir -p "$OUTPUT_DIR"

  # 화자구분 + JSON 출력
  DIARIZE_ARGS=(--diarize --output-format json -o "$OUTPUT_DIR")
  if [ -n "$NUM_SPEAKERS" ]; then
    DIARIZE_ARGS+=(--num-speakers "$NUM_SPEAKERS")
  fi

  "$MLX_ASR_BIN" "${COMMON_ARGS[@]}" \
    "${DIARIZE_ARGS[@]}" \
    "$AUDIO_PATH"

  # 생성된 JSON 파일 찾기
  AUDIO_BASE=$(basename "$AUDIO_PATH")
  AUDIO_STEM="${AUDIO_BASE%.*}"
  JSON_PATH="$OUTPUT_DIR/${AUDIO_STEM}.json"
  if [ ! -f "$JSON_PATH" ]; then
    JSON_PATH=$(find "$OUTPUT_DIR" -maxdepth 1 -name "*.json" -print -quit)
    if [ -z "$JSON_PATH" ] || [ ! -f "$JSON_PATH" ]; then
      echo "ERROR: JSON 출력 파일을 찾을 수 없습니다: $OUTPUT_DIR" >&2
      exit 1
    fi
  fi

  # JSON → 포맷팅된 txt 변환
  "$PYTHON_BIN" "$SCRIPT_DIR/format-transcript.py" "$JSON_PATH"
else
  # 기존 동작: stdout 텍스트 출력
  "$MLX_ASR_BIN" "${COMMON_ARGS[@]}" \
    --stdout-only \
    "$AUDIO_PATH"
fi
