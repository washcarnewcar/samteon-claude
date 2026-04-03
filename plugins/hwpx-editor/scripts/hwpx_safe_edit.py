#!/usr/bin/env python3
"""HWPX 안전 편집 유틸리티.

텍스트 치환 + linesegarray 제거 + 이미지 교체를 안전하게 수행한다.

핵심 원칙:
  - 텍스트 수정 후 hp:linesegarray를 반드시 제거 (미제거 시 "문서 손상" 오류)
  - 한글이 파일을 열 때 linesegarray를 자동 재계산함

Usage:
    ~/.claude/venv/bin/python hwpx_safe_edit.py input.hwpx output.hwpx \\
        --replace "기존 텍스트=새 텍스트" \\
        --replace "또 다른 기존=또 다른 새" \\
        --replace-image "BinData/image2.png=/path/to/new.png" \\
        --remove-all-lineseg
"""

import argparse
import sys
from pathlib import Path

from hwpx import HwpxPackage

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def safe_edit(
    input_path: str,
    output_path: str,
    text_replacements: list[tuple[str, str]] | None = None,
    image_replacements: dict[str, str] | None = None,
    remove_all_lineseg: bool = False,
) -> dict:
    """HWPX 파일을 안전하게 편집한다.

    Args:
        input_path: 입력 HWPX 파일 경로
        output_path: 출력 HWPX 파일 경로
        text_replacements: (기존 텍스트, 새 텍스트) 튜플 리스트
        image_replacements: {BinData/imageN.png: 새 이미지 파일 경로} 딕셔너리
        remove_all_lineseg: True면 모든 linesegarray 제거, False면 수정된 문단만

    Returns:
        편집 결과 통계 딕셔너리
    """
    pkg = HwpxPackage.open(input_path)
    stats = {"text_replaced": 0, "images_replaced": 0, "lineseg_removed": 0}

    # 1. 이미지 교체
    if image_replacements:
        for part_name, img_path in image_replacements.items():
            with open(img_path, "rb") as f:
                pkg.set_part(part_name, f.read())
            stats["images_replaced"] += 1

    # 2. 텍스트 치환 + linesegarray 제거
    if text_replacements:
        for sp in pkg.section_paths():
            tree = pkg.get_xml(sp)

            if remove_all_lineseg:
                # 모든 linesegarray 제거 (가장 안전)
                for lsa in tree.findall(f".//{{{HP}}}linesegarray"):
                    lsa.getparent().remove(lsa)
                    stats["lineseg_removed"] += 1

            # lxml에서 텍스트 치환
            modified_paras = set()
            for t_elem in tree.iter(f"{{{HP}}}t"):
                if t_elem.text is None:
                    continue
                for old_text, new_text in text_replacements:
                    if old_text in t_elem.text:
                        t_elem.text = t_elem.text.replace(old_text, new_text)
                        stats["text_replaced"] += 1

                        if not remove_all_lineseg:
                            # 수정된 문단의 linesegarray만 제거
                            node = t_elem
                            while node is not None:
                                if node.tag == f"{{{HP}}}p":
                                    p_id = id(node)
                                    if p_id not in modified_paras:
                                        modified_paras.add(p_id)
                                        for lsa in node.findall(
                                            f"{{{HP}}}linesegarray"
                                        ):
                                            node.remove(lsa)
                                            stats["lineseg_removed"] += 1
                                    break
                                node = node.getparent()
                        break

            pkg.set_xml(sp, tree)

    # 3. 저장
    pkg.save(output_path)

    return stats


def main():
    parser = argparse.ArgumentParser(description="HWPX 안전 편집 유틸리티")
    parser.add_argument("input", help="입력 HWPX 파일")
    parser.add_argument("output", help="출력 HWPX 파일")
    parser.add_argument(
        "--replace",
        action="append",
        default=[],
        help='텍스트 치환 "기존=새" (여러 번 사용 가능)',
    )
    parser.add_argument(
        "--replace-image",
        action="append",
        default=[],
        help='이미지 교체 "BinData/imageN.png=/path/to/new.png" (여러 번 사용 가능)',
    )
    parser.add_argument(
        "--remove-all-lineseg",
        action="store_true",
        help="모든 linesegarray 제거 (기본: 수정된 문단만)",
    )
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"파일을 찾을 수 없습니다: {args.input}", file=sys.stderr)
        sys.exit(1)

    text_reps = []
    for r in args.replace:
        if "=" not in r:
            print(f"잘못된 형식: {r} (올바른 형식: '기존=새')", file=sys.stderr)
            sys.exit(1)
        old, new = r.split("=", 1)
        text_reps.append((old, new))

    image_reps = {}
    for r in args.replace_image:
        if "=" not in r:
            print(
                f"잘못된 형식: {r} (올바른 형식: 'BinData/imageN.png=/path/to/new.png')",
                file=sys.stderr,
            )
            sys.exit(1)
        part_name, img_path = r.split("=", 1)
        if not Path(img_path).exists():
            print(f"이미지 파일을 찾을 수 없습니다: {img_path}", file=sys.stderr)
            sys.exit(1)
        image_reps[part_name] = img_path

    stats = safe_edit(
        args.input,
        args.output,
        text_replacements=text_reps or None,
        image_replacements=image_reps or None,
        remove_all_lineseg=args.remove_all_lineseg,
    )

    print(f"텍스트 {stats['text_replaced']}개 치환")
    print(f"이미지 {stats['images_replaced']}개 교체")
    print(f"linesegarray {stats['lineseg_removed']}개 제거")
    print(f"저장: {args.output}")


if __name__ == "__main__":
    main()
