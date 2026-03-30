#!/usr/bin/env python3
"""JSON 전사 결과를 포맷팅된 txt로 변환한다.

Usage: format-transcript.py <json_file>
stdout: 생성된 txt 파일 경로
stderr: 감지된 화자 수
"""

import json
import os
import re
import sys

SKIP_RE = re.compile(r"[\s,.\?!;:。，？！、\-\"'\(\)\[\]…·\u3000]+")


def main():
    if len(sys.argv) < 2:
        print("ERROR: JSON 파일 경로가 필요합니다.", file=sys.stderr)
        print("Usage: format-transcript.py <json_file>", file=sys.stderr)
        sys.exit(1)

    json_path = sys.argv[1]
    if not os.path.isfile(json_path):
        print(f"ERROR: 파일을 찾을 수 없습니다: {json_path}", file=sys.stderr)
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    text = data.get("text", "")
    segments = data.get("segments", [])

    if not segments:
        print("감지된 화자: 0명 (화자구분 없음)", file=sys.stderr)
        lines = [text]
    else:
        lines = _format_with_speakers(text, segments)

    txt_path = os.path.splitext(json_path)[0] + ".txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")

    print(txt_path)


def _format_with_speakers(text, segments):
    """word-level segments의 화자 라벨 + text의 정상 띄어쓰기를 결합."""

    # 1. word segments를 같은 화자끼리 그룹핑
    turns = []
    for seg in segments:
        sp = seg.get("speaker", "SPEAKER_00")
        word = seg["text"].strip()
        if not word:
            continue
        if turns and turns[-1]["speaker"] == sp:
            turns[-1]["words"].append(word)
        else:
            turns.append({"speaker": sp, "words": [word]})

    # 2. text에서 공백+구두점 제거한 버전 + 원본 위치 매핑
    stripped = ""
    pos_map = []
    for i, c in enumerate(text):
        if not SKIP_RE.match(c):
            pos_map.append(i)
            stripped += c

    # 3. 화자 매핑
    speaker_map = {}
    for turn in turns:
        sp = turn["speaker"]
        if sp not in speaker_map:
            speaker_map[sp] = f"참석자 {len(speaker_map) + 1}"

    num_speakers = len(speaker_map)
    print(f"감지된 화자: {num_speakers}명", file=sys.stderr)

    # 4. 각 턴의 words를 stripped text에서 매칭 → 원본 text에서 추출
    search_pos = 0
    result = []

    for turn in turns:
        label = speaker_map[turn["speaker"]]
        needle = "".join(turn["words"])
        if not needle:
            continue

        idx = stripped.find(needle, search_pos)
        if idx != -1:
            orig_start = pos_map[idx]
            orig_end = pos_map[min(idx + len(needle) - 1, len(pos_map) - 1)] + 1
            chunk = text[orig_start:orig_end].strip()
            search_pos = idx + len(needle)
        else:
            # 매칭 실패 시 word-join 폴백
            chunk = " ".join(turn["words"])

        if chunk:
            result.append((label, chunk))

    # 5. 같은 화자 연속 합치기
    merged = []
    for label, txt in result:
        if merged and merged[-1][0] == label:
            merged[-1] = (label, merged[-1][1] + " " + txt)
        else:
            merged.append((label, txt))

    return [f"{label}: {txt}" for label, txt in merged]


if __name__ == "__main__":
    main()
