---
name: hwpx-editor
description: |
  Use when:
  - User asks to edit, modify, or add content to an existing HWPX (한글) document
  - User asks to create a new HWPX document
  - User says "한글 문서 수정", "HWPX 편집", "보고서에 내용 추가" etc.
  - User runs /hwpx-edit command
allowed-tools: Bash, Read, Write, Glob, Grep
---

# HWPX 문서 편집/생성

## Overview

python-hwpx 라이브러리(v2.9.0+)를 사용하여 HWPX(한글) 문서를 안전하게 편집하거나 생성하는 스킬. **기존 문서의 구조와 스타일 패턴을 분석하고, 그 패턴을 그대로 따라가며** 내용을 추가/수정한다.

## When to Use

- 기존 HWPX 문서에 섹션, 문단, 표를 추가할 때
- HWPX 문서의 텍스트를 수정할 때
- 목차가 있는 문서에 내용을 추가하여 목차도 함께 업데이트해야 할 때
- 새 HWPX 문서를 처음부터 생성할 때

**NOT for:**
- HWP(v5 바이너리) 파일 (HWPX로 변환 후 사용)
- 암호화된 HWPX 파일
- 이미지만 삽입하는 작업 (한글에서 수동 삽입이 더 빠름)

## Prerequisites

```bash
# python-hwpx 설치 확인
~/.claude/venv/bin/pip show python-hwpx

# 없으면 설치
~/.claude/venv/bin/pip install python-hwpx
```

의존성: `python-hwpx >= 2.9.0`, `lxml`

## 핵심 원칙

### 1. 기존 패턴을 관찰하고 따라가라

HWPX 문서마다 구조가 다르다. 문단이 섹션 루트에 직접 있을 수도 있고, 외곽 테이블의 subList 안에 중첩되어 있을 수도 있고, 또 다른 구조일 수도 있다. **문서의 구조를 미리 가정하지 말고**, `hwpx_analyze.py`의 분석 결과를 보고 콘텐츠가 실제로 어디에 어떻게 배치되어 있는지 파악한 뒤, 같은 위치와 스타일로 새 콘텐츠를 추가한다.

### 2. 절대 규칙

| # | 원칙 | 설명 |
|---|------|------|
| 1 | **⚠️ linesegarray 제거** | **텍스트 수정 후 해당 문단의 `hp:linesegarray`를 반드시 제거.** 미제거 시 한글이 "문서 손상"으로 판단. 한글이 열 때 자동 재계산함. ([한컴 공식 답변](https://forum.developer.hancom.com/t/hwpx-section0-xml/2414)) |
| 2 | **라이브러리 API 우선** | `add_paragraph()`, `add_table()`, `set_cell_text()` 등 고수준 API를 먼저 시도 |
| 3 | **XML 직접 생성 금지** | `etree.SubElement()`로 새 요소를 처음부터 만들면 형식이 깨짐 |
| 4 | **deepcopy 패턴** | 스타일 불일치나 위치 문제 시, 기존 유사 요소를 `deepcopy()` → 텍스트만 교체 |
| 5 | **분석 먼저** | 편집 전 반드시 `hwpx_analyze.py` 실행하여 문서 패턴 파악 |
| 6 | **목차 빠뜨리지 않기** | 목차가 있는 문서에 섹션을 추가하면 목차도 반드시 업데이트 |
| 7 | **페이지 번호는 사용자 확인** | 프로그래밍으로 계산 불가 → 한글에서 확인 후 사용자에게 요청 |
| 8 | **이미지 교체 가능** | BinData 파일 직접 교체로 이미지 교체 가능. 새 이미지 삽입(`<hp:pic>` 생성)은 미지원 → 한글에서 수동 |
| 9 | **수정본 별도 저장** | 원본을 덮어쓰지 않고 ` - 수정본.hwpx` 접미사로 별도 저장 |

## HWPX 참고 지식

| 항목 | 설명 |
|------|------|
| **스타일 ID** | `paraPrIDRef`(문단), `charPrIDRef`(글자), `borderFillIDRef`(표 테두리/배경) — 문서마다 다르므로 분석 필수 |
| **linesegarray** | 텍스트 줄 단위 레이아웃 캐시(위치, 높이, 줄바꿈). **텍스트 수정 후 반드시 제거**해야 하며, 미제거 시 "문서 손상" 오류 발생. 한글이 열 때 자동 재계산. |
| **이미지 교체** | HWPX ZIP 내 `BinData/imageN.png` 파일을 직접 교체하면 됨. 같은 파일명이면 header.xml 수정 불필요 |
| **XML 이스케이프** | `<hp:t>` 내에서 `<`, `>`는 `&lt;`, `&gt;`로 이스케이프됨. 바이트 치환 시 이스케이프 형태로 검색해야 함 |
| **목차 탭 너비** | 목차의 점선 탭 너비는 텍스트/페이지 번호 자릿수에 의존. 자릿수 변화 시 ±600 HWPUNIT 조정 |
| **HWPUNIT** | 좌표 단위. 7200 = 1인치. 1px(96DPI) = 75 HWPUNIT |
| **네임스페이스** | `hp:` (paragraph), `hs:` (section), `hc:` (core), `hh:` (head) |

## Procedure: 편집 모드 (기존 문서 수정)

### Phase 1: 문서 패턴 파악

**반드시 먼저 실행:**

```bash
~/.claude/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/hwpx_analyze.py <파일.hwpx>
```

분석 스크립트가 출력하는 정보:
- **콘텐츠 경로**: 실제 본문 콘텐츠가 위치한 XML 트리 경로
- **스타일 매핑**: 소제목, 본문, 표 헤더/본문에 사용되는 스타일 ID
- **목차**: 유무, 항목 목록, 페이지 번호, 탭 너비
- **표**: 각 표의 행/열 수, 열 너비, borderFillIDRef
- **삽입 지점**: 마지막 콘텐츠 위치

분석 결과를 읽고, **이 문서의 콘텐츠가 어떤 패턴으로 구성되어 있는지** 이해한다. 그 다음 수정 계획을 세운다.

### Phase 2: 수정 계획

분석 결과를 바탕으로:
1. **삽입 위치 결정**: 분석에서 보여준 콘텐츠 경로의 끝부분
2. **스타일 선택**: 분석에서 발견된 기존 스타일 ID 사용
3. **deepcopy 소스 선정**: 추가할 요소와 가장 유사한 기존 요소 식별 (소제목이면 기존 소제목, 표면 기존 표)
4. **목차 업데이트 계획**: 새 항목 추가 여부, 기존 페이지 번호 변경 여부
5. **이미지 자리**: 이미지가 필요하면 자리 표시 문단 계획

### Phase 3: 수정 실행

**고수준 API로 시도하고, 결과를 한글에서 확인한다.** 위치나 스타일이 맞지 않으면 deepcopy 패턴으로 전환한다.

#### 방법 A: 고수준 API

```python
from hwpx import HwpxDocument

doc = HwpxDocument.open(INPUT_PATH)
section = doc.sections[0]

doc.add_paragraph("텍스트", section=section,
    para_pr_id_ref=<분석에서 발견된 ID>,
    char_pr_id_ref=<분석에서 발견된 ID>)

table = doc.add_table(rows=N, cols=M, section=section, width=<분석에서 발견된 너비>)
table.set_cell_text(0, 0, "헤더")

doc.save_to_path(OUTPUT_PATH)
```

→ 한글에서 열어 확인. 위치/스타일 OK면 Phase 4로. 문제 있으면 방법 B.

#### 방법 B: deepcopy 패턴

고수준 API가 문서 패턴에 맞지 않을 때 사용. 기존 요소를 복사하므로 스타일이 자동으로 일치한다.

```python
from hwpx import HwpxPackage
from copy import deepcopy

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
ns = {'hp': HP}

pkg = HwpxPackage.open(INPUT_PATH)
tree = pkg.get_xml("Contents/section0.xml")

# 1. 분석 결과에서 알려준 콘텐츠 컨테이너 찾기
container = ...  # 분석 결과의 content_path 참조

# 2. 기존 유사 요소 deepcopy
existing = container.findall('hp:p', ns)[<유사한 문단 인덱스>]
new_elem = deepcopy(existing)

# 3. 텍스트만 교체
new_elem.find('.//hp:t', ns).text = "새 텍스트"

# 4. ⚠️ linesegarray 제거 (필수! 미제거 시 "문서 손상" 오류)
for lsa in new_elem.findall(f'{{{HP}}}linesegarray'):
    lsa.getparent().remove(lsa)

# 5. 삽입
container.append(new_elem)

pkg.set_xml("Contents/section0.xml", tree)
pkg.save(OUTPUT_PATH)
```

#### 방법 C: 바이트 치환 + linesegarray 제거 (기존 텍스트 대량 교체에 최적)

기존 문서의 텍스트를 대량으로 교체할 때 가장 안전한 방법. lxml 파싱→재직렬화 시 발생할 수 있는 네임스페이스/공백 변형 없이 텍스트만 정확히 교체한다.

```python
from hwpx import HwpxPackage
from lxml import etree

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"

pkg = HwpxPackage.open(INPUT_PATH)

# 1. XML 원본 바이트 가져오기
raw = pkg.get_text("Contents/section0.xml").encode('utf-8')

# 2. 바이트 단위 텍스트 치환
replacements = [("기존 텍스트", "새 텍스트"), ...]
for old, new in replacements:
    raw = raw.replace(old.encode('utf-8'), new.encode('utf-8'))

# ⚠️ XML 이스케이프 주의: 캡션의 <이름>은 &lt;이름&gt; 형태
raw = raw.replace(b"&lt;기존이름&gt;", b"&lt;새이름&gt;")

# 3. lxml로 파싱하여 linesegarray 제거 (필수!)
root = etree.fromstring(raw)
for lsa in root.findall(f'.//{{{HP}}}linesegarray'):
    lsa.getparent().remove(lsa)

# 4. 원본 XML 선언 보존하여 저장
decl = b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
modified = decl + etree.tostring(root)

# 5. set_xml은 Element를 받으므로 set_part로 바이트 직접 저장
pkg.set_part("Contents/section0.xml", modified)
pkg.save(OUTPUT_PATH)
```

#### 이미지 교체

HWPX ZIP 내의 `BinData/` 폴더에 있는 이미지 파일을 직접 교체한다.

```python
pkg = HwpxPackage.open(INPUT_PATH)

# 이미지 교체 (같은 파일명이면 header.xml 수정 불필요)
with open("new_screenshot.png", "rb") as f:
    pkg.set_part("BinData/image2.png", f.read())

pkg.save(OUTPUT_PATH)
```

### Phase 4: 목차 처리

**목차가 없으면 건너뜀.**

목차가 있는 문서에 새 섹션을 추가했다면:

1. **사용자에게 페이지 번호 확인 요청:**
   ```
   수정본을 한글에서 열어서 각 소제목의 실제 페이지 번호를 알려주세요:
   (1) xxx → ?페이지
   ...
   (새 항목) → ?페이지
   ```

2. **목차 수정 (deepcopy 패턴):**
   - 기존 목차 항목을 deepcopy하여 새 항목 추가
   - 페이지 번호 텍스트 교체
   - 탭 너비 조정 (자릿수 변화 시):
     - 페이지 번호 자릿수 증가 → 탭 너비 **-600**
     - 페이지 번호 자릿수 감소 → 탭 너비 **+600**
     - 항목번호 자릿수도 동일 규칙

3. **기존 항목의 페이지 번호가 바뀌었으면 함께 수정**

### Phase 5: 검증

한글에서 수정본을 열어 다음을 확인하도록 안내:
- 추가된 내용의 위치와 레이아웃
- 글꼴/크기가 기존 내용과 동일한지
- 표 테두리와 정렬
- 목차 항목과 페이지 번호
- 이미지 자리 표시 위치

## Procedure: 생성 모드 (새 문서 만들기)

### Phase 1: 문서 생성

```python
from hwpx import HwpxDocument

doc = HwpxDocument.new()
doc.add_paragraph("제목")
doc.add_paragraph("본문 텍스트")

table = doc.add_table(rows=3, cols=4, width=42000)
table.set_cell_text(0, 0, "헤더 1")

doc.save_to_path(OUTPUT_PATH)
```

### Phase 2: 스타일링

```python
paragraph = doc.add_paragraph("강조 텍스트")
paragraph.add_run("볼드", bold=True, underline=True)

doc.replace_text_in_runs("임시", "확정", text_color="#FF0000")
```

### Phase 3: 저장 후 한글에서 확인

## python-hwpx API 빠른 참조

| 용도 | 메서드 |
|------|--------|
| 파일 열기 | `HwpxDocument.open(path)` |
| 새 문서 | `HwpxDocument.new()` |
| 문단 추가 | `doc.add_paragraph(text, section=, para_pr_id_ref=, char_pr_id_ref=)` |
| 표 추가 | `doc.add_table(rows, cols, section=, width=, border_fill_id_ref=)` |
| 셀 텍스트 | `table.set_cell_text(row, col, text)` |
| 셀 병합 | `table.merge_cells(r1, c1, r2, c2)` |
| 텍스트 치환 | `doc.replace_text_in_runs(search, replacement)` |
| 텍스트 추출 | `TextExtractor(path).extract_text()` |
| 요소 검색 | `ObjectFinder(path).find_all(tag=...)` |
| XML 조회 | `doc.package.get_xml("Contents/section0.xml")` |
| XML 저장 | `doc.package.set_xml(part_name, element)` |
| 파일 저장 | `doc.save_to_path(output_path)` |
| 바이트 저장 | `doc.to_bytes()` |

## Common Mistakes

| 실수 | 올바른 방법 |
|------|-----------|
| 문서 구조를 미리 가정 | `hwpx_analyze.py`로 실제 패턴 파악 후 진행 |
| `etree.SubElement()`로 XML 직접 생성 | 기존 요소 `deepcopy()` → 텍스트만 교체 |
| 스타일 ID 하드코딩 | 대상 문서에서 분석한 스타일 ID 사용 |
| 콘텐츠 위치 확인 안 함 | 분석 결과의 콘텐츠 경로를 확인하고 해당 위치에 삽입 |
| 목차 업데이트 깜빡함 | 목차 있는 문서에 섹션 추가 시 Phase 4 반드시 수행 |
| 목차 탭 너비 미조정 | 페이지/항목 자릿수 변화 시 ±600 HWPUNIT |
| ⚠️ linesegarray 그대로 둠 | **텍스트 수정한 문단의 linesegarray 반드시 제거.** 미제거 시 "문서 손상" 오류 |
| 추측으로 원인 추적 | 원인 불명 시 2~3회 실패하면 즉시 웹검색 (한컴 포럼 등) |
| 바이트 치환 시 XML 이스케이프 미적용 | `<이름>`은 XML에서 `&lt;이름&gt;` 형태. 이스케이프된 형태로 검색 |
| 원본 파일 덮어쓰기 | ` - 수정본.hwpx` 접미사로 별도 저장 |
| 새 이미지를 코드로 삽입 시도 | 기존 이미지 교체는 BinData 파일 교체로 가능. 새 이미지 삽입(`<hp:pic>`)은 한글에서 수동 |
| 한글에서 확인 안 함 | 저장 후 반드시 한글에서 열어 레이아웃 확인 |
