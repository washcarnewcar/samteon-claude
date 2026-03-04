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

## 이모지 폰트 설정

PDF에서 이모지 렌더링을 위해 NotoEmoji 폰트 다운로드 필요.

```python
import urllib.request
url = 'https://github.com/google/fonts/raw/main/ofl/notoemoji/NotoEmoji%5Bwght%5D.ttf'
urllib.request.urlretrieve(url, '/tmp/NotoEmoji.ttf')
```

**절대 금지:** 이모지를 다른 문자로 치환하지 말 것 (`👉` → `▶` 같은 치환 금지). 폰트로 해결.

## 변환 스크립트

```python
import markdown
from weasyprint import HTML

with open(md_path, 'r', encoding='utf-8') as f:
    md_content = f.read()

html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code', 'codehilite', 'toc'])

html_full = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
{CSS_TEMPLATE}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

HTML(string=html_full).write_pdf(pdf_path)
```

## CSS 테마

```css
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap');

@font-face {
    font-family: 'NotoEmoji';
    src: url('file:///tmp/NotoEmoji.ttf');
}

@page {
    size: A4;
    margin: 2cm 2cm 2.5cm 2cm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-family: 'Noto Sans KR', sans-serif;
        font-size: 9pt;
        color: #888;
    }
}

body {
    font-family: 'Noto Sans KR', 'NotoEmoji', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
    font-size: 10pt;
    line-height: 1.7;
    color: #222;
}

h1 {
    font-size: 18pt;
    font-weight: 700;
    color: #1a1a2e;
    border-bottom: 2.5px solid #1a1a2e;
    padding-bottom: 6px;
    margin-top: 28px;
    margin-bottom: 14px;
    page-break-after: avoid;
}

h1:first-child { margin-top: 0; }

h2 {
    font-size: 13pt;
    font-weight: 600;
    color: #16213e;
    border-bottom: 1px solid #ddd;
    padding-bottom: 4px;
    margin-top: 20px;
    margin-bottom: 10px;
    page-break-after: avoid;
}

h3 {
    font-size: 11pt;
    font-weight: 600;
    color: #0f3460;
    margin-top: 16px;
    margin-bottom: 8px;
}

p { margin: 6px 0; }

blockquote {
    border-left: 4px solid #3a86ff;
    background: #f0f4ff;
    margin: 12px 0;
    padding: 10px 16px;
    font-size: 9.5pt;
    color: #333;
}

blockquote strong { color: #1a1a2e; }

table {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
}

th {
    background-color: #1a1a2e;
    color: white;
    font-weight: 500;
    padding: 8px 10px;
    text-align: left;
    border: 1px solid #1a1a2e;
}

td {
    padding: 7px 10px;
    border: 1px solid #ddd;
    vertical-align: top;
}

tr:nth-child(even) td { background-color: #f8f9fa; }

code {
    font-family: 'D2Coding', 'Noto Sans Mono', 'Courier New', monospace;
    background: #f5f5f5;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 9pt;
    color: #c7254e;
}

pre {
    background: #2d2d2d;
    color: #f0f0f0;
    padding: 14px 16px;
    border-radius: 6px;
    font-size: 8.5pt;
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre-wrap;
    word-wrap: break-word;
    page-break-inside: avoid;
    margin: 10px 0;
}

pre code {
    background: none;
    color: #f0f0f0;
    padding: 0;
    font-size: 8.5pt;
}

hr {
    border: none;
    border-top: 1.5px solid #ddd;
    margin: 24px 0;
}

ul, ol { margin: 6px 0; padding-left: 24px; }
li { margin: 3px 0; }
strong { font-weight: 600; color: #1a1a2e; }
```

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
| 이모지 → 다른 문자 치환 | NotoEmoji 폰트 다운로드 + @font-face 사용 |
| CSS에서 `{{` 미사용 | f-string 내 CSS는 중괄호를 `{{` `}}`로 이스케이프 |
| Google Fonts @import 실패 | 오프라인 시 로컬 폰트 폴백으로 동작 |

## 검증

PDF 생성 후 Read 도구로 시각 확인:
```python
# 생성 후 확인
Read(file_path=pdf_path, pages="1-3")
```
