#!/usr/bin/env python3
"""HWPX 문서 구조 분석 유틸리티.

HWPX 파일을 분석하여 편집에 필요한 구조 정보를 JSON으로 출력한다.
- 콘텐츠 위치 (일반 구조 vs 프레임 구조)
- 스타일 ID 매핑
- 목차 정보
- 표 구조
- 삽입 지점

Usage:
    ~/.claude/venv/bin/python hwpx_analyze.py <파일.hwpx>
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from hwpx import HwpxPackage
from lxml import etree

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
NS = {"hp": HP, "hs": HS, "hh": HH}


def analyze_hwpx(path: str) -> dict:
    pkg = HwpxPackage.open(path)
    section_paths = pkg.section_paths()

    result = {
        "file": path,
        "sections": len(section_paths),
        "content_structure": [],
    }

    for sp in section_paths:
        tree = pkg.get_xml(sp)
        section_info = analyze_section(tree, sp)
        result["content_structure"].append(section_info)

    # header.xml 분석 (스타일 정보)
    for hp in pkg.header_paths():
        header_tree = pkg.get_xml(hp)
        result["header_styles"] = analyze_header(header_tree)

    # BinData 이미지 분석
    result["images"] = analyze_images(pkg)

    # linesegarray 통계
    result["linesegarray_info"] = analyze_linesegarray(pkg, section_paths)

    return result


def analyze_section(tree, section_path: str) -> dict:
    top_paras = tree.findall("hp:p", NS)
    info = {
        "section_path": section_path,
        "top_level_paragraphs": len(top_paras),
        "content_location": None,
        "content_paragraphs": [],
        "toc": None,
        "tables": [],
        "style_usage": {},
        "insertion_point": None,
    }

    # 콘텐츠 위치 탐색: 실제 본문 텍스트가 어디에 있는지 트리를 탐색
    content_location = find_content_location(top_paras)
    info["content_location"] = content_location

    container = content_location["container"]
    content_paras = container.findall("hp:p", NS) if container is not None else top_paras

    info["content_paragraph_count"] = len(content_paras)

    # 스타일 사용 분석
    style_counter = Counter()
    for i, p in enumerate(content_paras):
        para_pr = p.get("paraPrIDRef", "?")
        runs = p.findall("hp:run", NS)
        char_prs = [r.get("charPrIDRef", "?") for r in runs[:2]]
        texts = [t.text for t in p.findall(".//hp:t", NS) if t.text]
        text = " ".join(texts)[:80] if texts else ""
        has_tbl = len(p.findall(".//hp:tbl", NS)) > 0
        has_tab = len(p.findall(".//hp:tab", NS)) > 0

        style_key = f"paraPr={para_pr},charPr={','.join(char_prs)}"
        style_counter[style_key] += 1

        # 문단 요약 (처음 5개 + 마지막 5개)
        if i < 5 or i >= len(content_paras) - 5:
            info["content_paragraphs"].append({
                "index": i,
                "paraPrIDRef": para_pr,
                "charPrIDRef": char_prs,
                "text": text,
                "has_table": has_tbl,
                "has_tab": has_tab,
            })

    # 스타일 사용 빈도
    info["style_usage"] = dict(style_counter.most_common(10))

    # 스타일 분류 추정
    info["style_map"] = classify_styles(content_paras)

    # 목차 감지
    info["toc"] = detect_toc(content_paras)

    # 표 분석
    info["tables"] = analyze_tables(content_paras)

    # 삽입 지점
    info["insertion_point"] = {
        "last_paragraph_index": len(content_paras) - 1,
        "content_path": content_location["path"],
    }

    return info


def find_content_location(top_paras: list) -> dict:
    """실제 본문 콘텐츠가 어디에 있는지 탐색.

    HWPX 문서는 다양한 구조로 콘텐츠를 배치할 수 있다.
    이 함수는 가장 많은 텍스트 문단을 포함하는 컨테이너를 찾아 반환한다.
    """
    # 각 후보 컨테이너의 텍스트 문단 수를 세서 가장 큰 것을 선택
    candidates = []

    # 후보 1: 섹션 루트 (top-level paragraphs 직접)
    root_text_count = sum(
        1 for p in top_paras
        if any(t.text for t in p.findall(".//hp:t", NS) if t.text)
        and not p.findall(".//hp:tbl", NS)
    )
    candidates.append({
        "path": "section root",
        "description": "섹션 루트에 직접 배치된 문단",
        "paragraph_count": len(top_paras),
        "text_paragraph_count": root_text_count,
        "container": None,  # top_paras 자체
    })

    # 후보 2+: subList 안에 있는 콘텐츠
    for i, p in enumerate(top_paras):
        for tbl in p.findall(".//hp:tbl", NS):
            row_cnt = tbl.get("rowCnt", "0")
            col_cnt = tbl.get("colCnt", "0")
            for sl in tbl.findall(".//hp:subList", NS):
                inner_paras = sl.findall("hp:p", NS)
                inner_text_count = sum(
                    1 for ip in inner_paras
                    if any(t.text for t in ip.findall(".//hp:t", NS) if t.text)
                )
                if inner_text_count > 3:
                    candidates.append({
                        "path": f"P[{i}] > tbl({row_cnt}x{col_cnt}) > subList",
                        "description": f"문단 P[{i}] 내부 표({row_cnt}x{col_cnt})의 subList",
                        "paragraph_count": len(inner_paras),
                        "text_paragraph_count": inner_text_count,
                        "container": sl,
                    })

    # 가장 많은 텍스트 문단을 가진 컨테이너 선택
    best = max(candidates, key=lambda c: c["text_paragraph_count"])

    # container가 None이면 섹션 루트 → 별도 처리 불필요
    return {
        "path": best["path"],
        "description": best["description"],
        "paragraph_count": best["paragraph_count"],
        "text_paragraph_count": best["text_paragraph_count"],
        "container": best["container"],
        "all_candidates": [
            {k: v for k, v in c.items() if k != "container"}
            for c in candidates
        ],
    }


def classify_styles(paras: list) -> dict:
    """문단들의 스타일을 분석하여 용도별로 분류."""
    styles = {
        "subtitle": None,
        "body_text": None,
        "table_paragraph": None,
    }

    subtitle_pattern = re.compile(r"^\(\d+\)\s")
    subtitle_styles = []
    body_styles = []

    for p in paras:
        texts = [t.text for t in p.findall(".//hp:t", NS) if t.text]
        text = " ".join(texts)
        has_tbl = len(p.findall(".//hp:tbl", NS)) > 0
        para_pr = p.get("paraPrIDRef", "?")
        runs = p.findall("hp:run", NS)
        char_pr = runs[0].get("charPrIDRef", "?") if runs else "?"

        if subtitle_pattern.match(text):
            subtitle_styles.append({"paraPrIDRef": para_pr, "charPrIDRef": char_pr})
        elif text and not has_tbl and len(text) > 20:
            body_styles.append({"paraPrIDRef": para_pr, "charPrIDRef": char_pr})

    if subtitle_styles:
        counter = Counter(str(s) for s in subtitle_styles)
        most_common = eval(counter.most_common(1)[0][0])
        styles["subtitle"] = most_common

    if body_styles:
        counter = Counter(str(s) for s in body_styles)
        most_common = eval(counter.most_common(1)[0][0])
        styles["body_text"] = most_common

    return styles


def detect_toc(paras: list) -> dict | None:
    """목차(Table of Contents) 감지."""
    toc_items = []

    for i, p in enumerate(paras):
        tabs = p.findall(".//hp:tab", NS)
        if not tabs:
            continue

        texts = p.findall(".//hp:t", NS)
        text_parts = [t.text for t in texts if t.text]

        if len(text_parts) >= 2:
            title = text_parts[0].strip()
            page = text_parts[-1].strip()

            if page.isdigit() and len(title) > 2:
                tab_width = tabs[0].get("width", "0") if tabs else "0"
                toc_items.append({
                    "paragraph_index": i,
                    "title": title,
                    "page": page,
                    "tab_width": tab_width,
                })

    if len(toc_items) >= 3:
        return {
            "detected": True,
            "item_count": len(toc_items),
            "items": toc_items,
            "first_item_index": toc_items[0]["paragraph_index"],
            "last_item_index": toc_items[-1]["paragraph_index"],
        }
    return None


def analyze_tables(paras: list) -> list:
    """문서 내 표 분석."""
    tables = []

    for i, p in enumerate(paras):
        for tbl in p.findall(".//hp:tbl", NS):
            row_cnt = tbl.get("rowCnt", "?")
            col_cnt = tbl.get("colCnt", "?")
            border_fill = tbl.get("borderFillIDRef", "?")

            sz = tbl.find("hp:sz", NS)
            width = sz.get("width", "?") if sz is not None else "?"

            # 열 너비
            trs = tbl.findall("hp:tr", NS)
            col_widths = []
            if trs:
                first_row_cells = trs[0].findall("hp:tc", NS)
                for tc in first_row_cells:
                    cell_sz = tc.find("hp:cellSz", NS)
                    if cell_sz is not None:
                        col_widths.append(cell_sz.get("width", "?"))

            # 헤더/본문 셀 스타일
            header_style = None
            body_style = None
            if trs:
                first_row = trs[0]
                first_tc = first_row.findall("hp:tc", NS)
                if first_tc:
                    header_style = first_tc[0].get("borderFillIDRef", "?")
                if len(trs) > 1:
                    body_tc = trs[1].findall("hp:tc", NS)
                    if body_tc:
                        body_style = body_tc[0].get("borderFillIDRef", "?")

            # 첫 행 텍스트 (헤더 추정)
            header_texts = []
            if trs:
                for tc in trs[0].findall("hp:tc", NS):
                    tc_texts = [t.text for t in tc.findall(".//hp:t", NS) if t.text]
                    header_texts.append(" ".join(tc_texts))

            tables.append({
                "paragraph_index": i,
                "rows": row_cnt,
                "cols": col_cnt,
                "width": width,
                "col_widths": col_widths,
                "borderFillIDRef": border_fill,
                "header_borderFillIDRef": header_style,
                "body_borderFillIDRef": body_style,
                "header_texts": header_texts,
            })

    return tables


def analyze_images(pkg) -> list:
    """BinData 폴더의 이미지 파일 분석."""
    images = []
    for name in pkg.part_names():
        if name.startswith("BinData/"):
            data = pkg.get_part(name)
            images.append({
                "name": name,
                "size": len(data),
                "size_kb": round(len(data) / 1024, 1),
            })
    return images


def analyze_linesegarray(pkg, section_paths: list) -> dict:
    """linesegarray 존재 여부 및 개수 분석.

    ⚠️ 텍스트 수정 시 해당 문단의 linesegarray를 제거해야 함.
    미제거 시 한글에서 "문서 손상" 오류 발생.
    """
    total = 0
    for sp in section_paths:
        tree = pkg.get_xml(sp)
        count = len(tree.findall(f".//{{{HP}}}linesegarray"))
        total += count
    return {
        "total_count": total,
        "warning": "텍스트 수정 후 해당 문단의 linesegarray를 반드시 제거해야 합니다 (한컴 공식 가이드)",
    }


def analyze_header(header_tree) -> dict:
    """header.xml에서 스타일 정의 분석."""
    styles = []

    for style in header_tree.iter():
        if "style" in style.tag.lower() and style.get("name"):
            styles.append({
                "name": style.get("name"),
                "id": style.get("id"),
                "type": style.get("type", ""),
            })

    return {"style_count": len(styles), "styles": styles[:20]}


def print_report(analysis: dict):
    """분석 결과를 읽기 쉬운 형태로 출력."""
    print("=" * 60)
    print(f"HWPX 문서 분석: {analysis['file']}")
    print(f"섹션 수: {analysis['sections']}")
    print("=" * 60)

    # 이미지
    images = analysis.get("images", [])
    if images:
        print(f"\n[이미지 {len(images)}개]")
        for img in images:
            print(f"  {img['name']} ({img['size_kb']}KB)")

    # linesegarray
    lsa_info = analysis.get("linesegarray_info", {})
    if lsa_info:
        print(f"\n[linesegarray] {lsa_info['total_count']}개")
        print(f"  ⚠️ {lsa_info['warning']}")

    for sec in analysis["content_structure"]:
        print(f"\n--- {sec['section_path']} ---")

        # 콘텐츠 위치
        loc = sec["content_location"]
        print(f"\n[콘텐츠 위치] {loc['path']}")
        print(f"  {loc['description']}")
        print(f"  문단 수: {loc['paragraph_count']} (텍스트 포함: {loc['text_paragraph_count']})")
        if len(loc.get("all_candidates", [])) > 1:
            print(f"  탐색된 다른 위치:")
            for c in loc["all_candidates"]:
                if c["path"] != loc["path"]:
                    print(f"    - {c['path']}: 문단 {c['paragraph_count']}개 (텍스트 {c['text_paragraph_count']}개)")

        print(f"\n콘텐츠 문단 수: {sec['content_paragraph_count']}")

        # 스타일 매핑
        sm = sec["style_map"]
        print(f"\n[스타일 매핑 (자동 분류)]")
        if sm.get("subtitle"):
            print(f"  소제목: paraPrIDRef={sm['subtitle']['paraPrIDRef']}, charPrIDRef={sm['subtitle']['charPrIDRef']}")
        if sm.get("body_text"):
            print(f"  본문:   paraPrIDRef={sm['body_text']['paraPrIDRef']}, charPrIDRef={sm['body_text']['charPrIDRef']}")

        # 목차
        toc = sec["toc"]
        if toc:
            print(f"\n[목차 감지] {toc['item_count']}개 항목 (P[{toc['first_item_index']}]~P[{toc['last_item_index']}])")
            for item in toc["items"]:
                print(f"  P[{item['paragraph_index']}] {item['title']:<40} → {item['page']}p (탭너비={item['tab_width']})")
        else:
            print(f"\n[목차 없음]")

        # 표
        if sec["tables"]:
            print(f"\n[표 {len(sec['tables'])}개]")
            for t in sec["tables"]:
                headers = ", ".join(t["header_texts"][:4])
                print(f"  P[{t['paragraph_index']}] {t['rows']}행×{t['cols']}열 (너비={t['width']}) [{headers}]")
                print(f"    열 너비: {t['col_widths']}")
                print(f"    borderFill: 헤더={t['header_borderFillIDRef']}, 본문={t['body_borderFillIDRef']}")

        # 삽입 지점
        ip = sec["insertion_point"]
        print(f"\n[삽입 지점] P[{ip['last_paragraph_index']}] 뒤 ({ip['content_path']})")

        # 문단 미리보기
        print(f"\n[문단 미리보기]")
        for p in sec["content_paragraphs"]:
            flags = ""
            if p["has_table"]:
                flags += " [TABLE]"
            if p["has_tab"]:
                flags += " [TAB]"
            print(f"  P[{p['index']}] paraPr={p['paraPrIDRef']} charPr={p['charPrIDRef']}{flags} {p['text'][:60]}")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <파일.hwpx>")
        sys.exit(1)

    path = sys.argv[1]
    if not Path(path).exists():
        print(f"파일을 찾을 수 없습니다: {path}")
        sys.exit(1)

    analysis = analyze_hwpx(path)

    # 읽기 쉬운 보고서 출력
    print_report(analysis)

    # lxml Element는 JSON 직렬화 불가 → 제거
    for sec in analysis["content_structure"]:
        if sec["content_location"]:
            del sec["content_location"]["container"]

    # JSON도 출력 (--json 옵션)
    if "--json" in sys.argv:
        print("\n\n=== JSON ===")
        print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
