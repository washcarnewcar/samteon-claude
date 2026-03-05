#!/usr/bin/env python3
"""Markdown to PDF converter with Navy theme, Korean fonts, and emoji support."""

import argparse
import os
import sys
import urllib.request

import markdown
from weasyprint import HTML

NOTO_EMOJI_PATH = "/tmp/NotoEmoji.ttf"
NOTO_EMOJI_URL = "https://github.com/google/fonts/raw/main/ofl/notoemoji/NotoEmoji%5Bwght%5D.ttf"

CSS = """
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
"""

MARKDOWN_EXTENSIONS = ["tables", "fenced_code", "codehilite", "toc"]


def ensure_emoji_font():
    if not os.path.exists(NOTO_EMOJI_PATH):
        print(f"Downloading NotoEmoji font to {NOTO_EMOJI_PATH}...", file=sys.stderr)
        urllib.request.urlretrieve(NOTO_EMOJI_URL, NOTO_EMOJI_PATH)


def convert(md_path: str, pdf_path: str):
    ensure_emoji_font()

    with open(md_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    html_body = markdown.markdown(md_content, extensions=MARKDOWN_EXTENSIONS)

    html_full = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
{CSS}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    HTML(string=html_full).write_pdf(pdf_path)
    print(f"PDF generated: {pdf_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Convert Markdown to styled PDF")
    parser.add_argument("input", help="Input Markdown file path")
    parser.add_argument("output", help="Output PDF file path")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    convert(args.input, args.output)


if __name__ == "__main__":
    main()
