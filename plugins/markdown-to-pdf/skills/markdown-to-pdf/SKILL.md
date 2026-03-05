---
name: markdown-to-pdf
description: "Use when converting Markdown files to styled PDF documents with Korean text, tables, code blocks, or emoji rendering"
allowed-tools: Bash, Read, Write
---

# Markdown → PDF 변환

## Overview

weasyprint + markdown 라이브러리로 마크다운을 전문적인 PDF로 변환. 네이비 테마, 한국어 폰트, 이모지 지원 포함.

## When to Use

- 마크다운 문서를 PDF로 변환해달라는 요청
- 한국어 텍스트가 포함된 PDF 생성
- 테이블, 코드 블록, 이모지가 포함된 문서

**NOT for:** docx 생성 (→ docx-report-generation 스킬), 단순 텍스트 출력

## 사전 요구사항

```bash
# macOS - pango 필수 (weasyprint 의존성)
brew install pango

# Python 패키지
pip3 install markdown weasyprint --break-system-packages
```

**절대 금지:** 이모지를 다른 문자로 치환하지 말 것. 스크립트가 NotoEmoji 폰트를 자동 다운로드하여 처리.

## 변환 방법

스크립트 경로: `plugins/markdown-to-pdf/scripts/md2pdf.py`

```bash
python3 <plugin_dir>/scripts/md2pdf.py <input.md> <output.pdf>
```

스크립트가 자동으로 처리하는 것:
- NotoEmoji 폰트 다운로드 (`/tmp/NotoEmoji.ttf` 없을 때)
- 네이비 테마 CSS 적용
- markdown extensions: tables, fenced_code, codehilite, toc
- 한국어 폰트 (Noto Sans KR) + 이모지 폰트 설정
- A4 사이즈, 페이지 번호 자동 삽입

## 테마 핵심 색상

| 요소 | 색상 | 용도 |
|------|------|------|
| `#1a1a2e` | 짙은 네이비 | h1, 테이블 헤더 배경, strong |
| `#16213e` | 네이비 | h2 |
| `#0f3460` | 진한 파랑 | h3 |
| `#2d2d2d` | 다크 그레이 | 코드 블록 배경 |
| `#c7254e` | 레드 핑크 | 인라인 코드 |
| `#3a86ff` | 블루 | blockquote 왼쪽 보더 |
| `#f0f4ff` | 연한 블루 | blockquote 배경 |

## Common Mistakes

| 실수 | 해결 |
|------|------|
| pango 미설치 | `brew install pango` 먼저 실행 |
| 이모지 → 다른 문자 치환 | 스크립트가 NotoEmoji 폰트를 자동 처리하므로 치환 금지 |
| Google Fonts @import 실패 | 오프라인 시 로컬 폰트 폴백으로 동작 |

## 검증

PDF 생성 후 Read 도구로 시각 확인:
```python
# 생성 후 확인
Read(file_path=pdf_path, pages="1-3")
```
