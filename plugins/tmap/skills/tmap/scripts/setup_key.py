#!/usr/bin/env python3
"""TMap API 키를 .local.md 파일에 저장.

사용법:
  python setup_key.py <키>           # 인자로 직접 지정
  python setup_key.py                 # 대화형 입력 (stdin)
"""
from __future__ import annotations

import getpass
import sys

from tmap_client import save_app_key


def main() -> int:
    if len(sys.argv) > 2:
        print("사용법: python setup_key.py [<키>]", file=sys.stderr)
        return 2

    if len(sys.argv) == 2:
        key = sys.argv[1]
    else:
        try:
            key = getpass.getpass("TMap AppKey 입력 (입력은 화면에 표시되지 않습니다): ")
        except (EOFError, KeyboardInterrupt):
            print("\n취소됨.", file=sys.stderr)
            return 1

    key = key.strip()
    if not key:
        print("빈 키는 저장할 수 없습니다.", file=sys.stderr)
        return 1

    path = save_app_key(key)
    print(f"TMap AppKey 저장 완료: {path}")
    print("이제 스크립트들을 사용할 수 있습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
