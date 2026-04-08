#!/bin/bash
set -euo pipefail
trap 'kill 0 2>/dev/null' TERM INT

# Usage:
#   transcribe.sh <audio_file>                                        # 일반 전사 (한국어, stdout 텍스트)
#   transcribe.sh --language English <audio_file>                     # 영어 전사
#   transcribe.sh --diarize <audio_file>                              # 화자구분 전사 (자동 감지)
#   transcribe.sh --diarize --num-speakers <N> <audio_file>           # 화자구분 전사 (화자 수 지정)
#   transcribe.sh --diarize --output <dir> <audio_file>               # 출력 디렉토리 지정

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

# ASR 상주 서버 체크
ASR_PORT="${ASR_PORT:-8787}"
ASR_URL="http://127.0.0.1:${ASR_PORT}"

if curl -sf "${ASR_URL}/health" > /dev/null 2>&1; then
  # 서버가 돌고 있으면 HTTP 요청 (빠른 경로)
  ABS_AUDIO="$(cd "$(dirname "$AUDIO_PATH")" && pwd)/$(basename "$AUDIO_PATH")"

  # JSON body 구성
  JSON_BODY="{\"audio_path\": \"${ABS_AUDIO}\", \"language\": \"${LANGUAGE}\""
  if [ "$DIARIZE" = true ]; then
    JSON_BODY="${JSON_BODY}, \"diarize\": true"
    if [ -n "$NUM_SPEAKERS" ]; then
      JSON_BODY="${JSON_BODY}, \"num_speakers\": ${NUM_SPEAKERS}"
    fi
  fi
  JSON_BODY="${JSON_BODY}}"

  RESPONSE=$(curl -sf -X POST "${ASR_URL}/transcribe" \
    -H "Content-Type: application/json" \
    -d "$JSON_BODY")

  if [ "$DIARIZE" = true ]; then
    # 화자구분: JSON → txt 변환
    if [ -z "$OUTPUT_DIR" ]; then
      OUTPUT_DIR=$(mktemp -d)
    fi
    mkdir -p "$OUTPUT_DIR"

    AUDIO_BASE=$(basename "$AUDIO_PATH")
    AUDIO_STEM="${AUDIO_BASE%.*}"
    TXT_PATH="$OUTPUT_DIR/${AUDIO_STEM}.txt"

    echo "$RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
segments = data.get('speaker_segments', [])
if segments:
    # 화자 라벨을 참석자 N 형태로 변환
    speakers = {}
    counter = 1
    lines = []
    for seg in segments:
        spk = seg['speaker']
        if spk not in speakers:
            speakers[spk] = f'참석자 {counter}'
            counter += 1
        lines.append(f\"{speakers[spk]}: {seg['text']}\")
    print('\n'.join(lines))
else:
    print(data.get('text', ''))
" > "$TXT_PATH"

    # 감지된 화자 수 출력
    SPEAKER_COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(set(s['speaker'] for s in d.get('speaker_segments',[]))))")
    echo "감지된 화자: ${SPEAKER_COUNT}명" >&2
    echo "$TXT_PATH"
  else
    # 일반 전사: 텍스트만 출력
    echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['text'])"
  fi
  exit 0
fi

# 공통 인자 (CLI fallback)
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
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  PYTHON_BIN="${PYTHON_BIN:-$HOME/.venvs/voice-transcriber/bin/python}"
  "$PYTHON_BIN" "$SCRIPT_DIR/format-transcript.py" "$JSON_PATH"
else
  # 기존 동작: stdout 텍스트 출력
  "$MLX_ASR_BIN" "${COMMON_ARGS[@]}" \
    --stdout-only \
    "$AUDIO_PATH"
fi
