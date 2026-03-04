---
name: docx-report-generation
description: "Use when building Word (.docx) reports containing charts, diagrams, or side-by-side visual comparisons on macOS with Korean text"
allowed-tools: Bash, Read, Write
---

# Word 보고서 생성

## Overview

python-docx로 한국어 보고서를 만들 때, 차트/다이어그램 삽입부터 PDF 변환, 자가 검토까지 검증된 패턴 모음. macOS + MS Word 환경 전용.

## When to Use

- python-docx로 보고서를 생성하고 차트/다이어그램을 삽입할 때
- 생성된 docx를 PDF로 변환하여 시각적으로 검증할 때
- 두 문서를 나란히 비교하는 이미지가 필요할 때
- macOS에서 한국어 파일명을 glob으로 검색해야 할 때

**NOT for:** 단순 텍스트 docx 생성, Windows 환경, 영어 전용 문서

## Quick Reference

| 작업 | 도구 | 핵심 |
|------|------|------|
| 다이어그램 | mermaid.ink API | `base64.urlsafe_b64encode()` → `https://mermaid.ink/img/{encoded}` |
| 차트 | matplotlib | `font.family: "Nanum Gothic"`, `axes.unicode_minus: False` |
| PDF 변환 | MS Word AppleScript | `open -g -a "Microsoft Word"` → `save as ... format PDF` |
| 비교 이미지 | PIL + pdf2image | 높이 맞춤 → 좌우 합성 → 라벨 |
| 파일 검색 | pathlib.glob | ASCII 패턴만, NFD→NFC 후처리 |

## Core Patterns

### Mermaid → PNG

```python
import base64, httpx
from pathlib import Path

def render_mermaid(mermaid_code: str, output_path: Path) -> Path:
    """mermaid.ink API로 Mermaid → PNG 변환."""
    encoded = base64.urlsafe_b64encode(
        mermaid_code.encode("utf-8")
    ).decode("ascii")
    url = f"https://mermaid.ink/img/{encoded}"
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    output_path.write_bytes(resp.content)
    return output_path
```

### matplotlib 한국어 설정

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.family": "Nanum Gothic",
    "font.size": 11,
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "savefig.bbox": "tight",
    "axes.unicode_minus": False,
})
```

### docx → PDF (MS Word, macOS)

5단계 순서:

1. `killall "Microsoft Word"` — 기존 프로세스 정리
2. `open -g -a "Microsoft Word" file.docx` — Launch Services로 열기 (샌드박스 팝업 우회)
3. JXA로 `activeDocument.name()` 폴링 — 문서 로딩 대기 (최대 15초)
4. AppleScript `save as ... file format format PDF` — PDF 저장
5. `killall "Microsoft Word"` — Word 종료

### 이미지 삽입 — 중앙 정렬 + 크기 조절

```python
def add_image(doc, img_path, width_cm=15.5, center=True):
    doc.add_picture(str(img_path), width=Cm(width_cm))
    if center:
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
```

크기 가이드:
- 가로 차트/비교 이미지: `width_cm=15.5` (전체 폭)
- Mermaid 세로(TD/TB): `width_cm=6~8` (좁게)
- Mermaid 가로(LR): `width_cm=12~15`
- 많은 항목 차트: `figsize` 폭 상한 14, 높이 비례 증가

### 자가 검토 루프

보고서 생성 후 **반드시** 수행. **이미지 크기는 한 번에 맞출 수 없다 — PDF를 보고 반복 조정이 원칙.**

1. MS Word로 PDF 변환
2. `pdf2image.convert_from_path()` → 전체 페이지 이미지화
3. 페이지 수 확인 (목표 범위 내인지)
4. Read 도구로 PDF 페이지 직접 시각 확인
5. 문제 발견 시 코드 수정 → 재생성 → 재검토 → **만족할 때까지 반복**

```
검토 체크리스트:
- [ ] 차트/다이어그램이 모두 정상 삽입되었는가
- [ ] Mermaid 텍스트가 잘리지 않았는가
- [ ] 비교 이미지가 올바른 문서를 비교하고 있는가
- [ ] 페이지 넘침으로 인한 공백 페이지가 없는가
- [ ] 이미지/차트가 적절한 크기인가 (빈 여백 과다, 납작한 차트 없는지)
- [ ] Mermaid 세로 다이어그램(TD/TB)이 페이지를 꽉 채우지 않는가
- [ ] 한국어 텍스트가 정상 렌더링되었는가
```

## Common Mistakes

| 실수 | 증상 | 해결 |
|------|------|------|
| LibreOffice로 PDF 변환 | 한국어 폰트 렌더링 차이, SSIM 저하 | **MS Word만 사용** (절대 규칙) |
| docx2pdf 패키지 사용 | Word 샌드박스 팝업 반복 | `open -g` + AppleScript 직접 사용 |
| Mermaid subgraph 제목 길게 | 렌더링 시 텍스트 잘림 | 15자 이내, 상세 내용은 노드 안에 |
| glob에 한국어 리터럴 | macOS NFD로 매칭 실패 | ASCII 패턴 + `unicodedata.normalize("NFC")` |
| 페이지 넘침 무시 | 이후 모든 페이지 정렬 깨짐 | 자가 검토에서 페이지 수 **먼저** 확인 |
| Mermaid 세로(TD/TB) 전체 폭 삽입 | 다이어그램이 페이지 꽉 참 | `width_cm=6~8`. 세로는 가로보다 좁게 |
| 많은 항목(50+) 차트 figsize 미제한 | 차트가 납작한 띠, 여백 과다 | `figsize` 폭 상한(14) 설정, 높이 비례 증가 |
| 섹션마다 강제 페이지 브레이크 | 이미지 뒤에 빈 여백 과다 | 불필요한 `doc.add_page_break()` 제거, 자연스러운 흐름 |
| 이미지 크기 한 번만 설정하고 끝냄 | 페이지에 비해 너무 크거나 작음 | **PDF로 보고 반복 조정** — 한 번에 안 맞는 게 정상 |
