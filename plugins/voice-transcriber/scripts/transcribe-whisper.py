#!/usr/bin/env python3
"""mlx-whisper 전사 CLI (transcribe.sh의 whisper 엔진 백엔드).

whisper_engine.WhisperEngine을 사용하여 전사한다.

Usage:
    # 일반 전사 (stdout으로 텍스트)
    transcribe-whisper.py --stdout-only --language Korean <audio>

    # 화자구분 전사 (<output_dir>/<stem>.json 생성)
    transcribe-whisper.py --diarize -o <output_dir> --language Korean <audio>
    transcribe-whisper.py --diarize --num-speakers 3 -o <output_dir> <audio>

화자구분 JSON 형식은 mlx-qwen3-asr 경로와 동일하게 {"text", "segments"}이며,
이후 format-transcript.py가 그대로 처리한다.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from whisper_engine import WhisperEngine, DEFAULT_WHISPER_MODEL  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="mlx-whisper transcription CLI")
    parser.add_argument("audio_path")
    parser.add_argument("--language", default="Korean")
    parser.add_argument("--model", default=DEFAULT_WHISPER_MODEL)
    parser.add_argument("--diarize", action="store_true")
    parser.add_argument("--num-speakers", type=int, default=None)
    parser.add_argument("-o", "--output-dir", default=None,
                        help="화자구분 JSON 출력 디렉토리")
    parser.add_argument("--stdout-only", action="store_true",
                        help="일반 전사 텍스트를 stdout으로 출력")
    args = parser.parse_args()

    if not os.path.isfile(args.audio_path):
        print(f"ERROR: 파일을 찾을 수 없습니다: {args.audio_path}", file=sys.stderr)
        sys.exit(1)

    engine = WhisperEngine(args.model)

    try:
        result = engine.transcribe(
            args.audio_path,
            language=args.language,
            diarize=args.diarize,
            num_speakers=args.num_speakers,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if not args.diarize:
        # 일반 전사: 텍스트만 stdout
        print(result.get("text", ""))
        return

    # 화자구분: {"text", "segments"} JSON을 <output_dir>/<stem>.json으로 저장
    output_dir = args.output_dir or "."
    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.audio_path))[0]
    json_path = os.path.join(output_dir, f"{stem}.json")

    payload = {
        "text": result.get("text", ""),
        "segments": result.get("speaker_segments", []),
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    # transcribe.sh가 경로를 알 수 있도록 stderr로 안내(표준 출력은 비워둠)
    print(f"[whisper] 화자구분 JSON 저장: {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
