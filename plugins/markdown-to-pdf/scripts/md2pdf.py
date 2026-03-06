#!/usr/bin/env python3
"""Markdown to PDF converter with theme support, Korean fonts, and emoji support."""

import argparse
import os
import re
import sys
import urllib.request

import markdown
from weasyprint import HTML

NOTO_EMOJI_PATH = "/tmp/NotoEmoji.ttf"
NOTO_EMOJI_URL = "https://github.com/google/fonts/raw/main/ofl/notoemoji/NotoEmoji%5Bwght%5D.ttf"

D2CODING_PATH = "/tmp/D2Coding.ttf"
D2CODING_URL = "https://cdn.jsdelivr.net/gh/joungkyun/font-d2coding@1.3.2/D2Coding.ttf"

CSS_BASE = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap');

@font-face {
    font-family: 'NotoEmoji';
    src: url('file:///tmp/NotoEmoji.ttf');
}

@font-face {
    font-family: 'D2Coding';
    src: url('file:///tmp/D2Coding.ttf');
}

@page {
    size: A4;
    margin: 2cm 2cm 2.5cm 2cm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-family: 'Noto Sans KR', sans-serif;
        font-size: 7pt;
        color: #888;
    }
}

body {
    font-family: 'Noto Sans KR', 'NotoEmoji', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
    font-size: 8pt;
    line-height: 1.7;
    color: #222;
}

p { margin: 6px 0; }

table {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 7.5pt;
    page-break-inside: avoid;
}

td {
    padding: 7px 10px;
    vertical-align: top;
}

code {
    font-family: 'D2Coding', 'Noto Sans Mono', 'Courier New', monospace;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 7pt;
}

pre {
    padding: 14px 16px;
    border-radius: 6px;
    font-size: 7pt;
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre;
    page-break-inside: avoid;
    margin: 10px 0;
}

pre code {
    background: none;
    padding: 0;
    font-size: 7pt;
}

hr {
    border: none;
    border-top: 1.5px solid #ddd;
    margin: 24px 0;
}

ul, ol { margin: 6px 0; padding-left: 24px; }
li { margin: 3px 0; }
.task-list-item { list-style-type: none; margin-left: -24px; }
"""

CSS_NAVY = CSS_BASE + """
h1 {
    font-size: 14pt;
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
    font-size: 10pt;
    font-weight: 600;
    color: #16213e;
    border-bottom: 1px solid #ddd;
    padding-bottom: 4px;
    margin-top: 20px;
    margin-bottom: 10px;
    page-break-after: avoid;
}

h3 {
    font-size: 9pt;
    font-weight: 600;
    color: #0f3460;
    margin-top: 16px;
    margin-bottom: 8px;
}

blockquote {
    border-left: 4px solid #3a86ff;
    background: #f0f4ff;
    margin: 12px 0;
    padding: 10px 16px;
    font-size: 7.5pt;
    color: #333;
}

blockquote strong { color: #1a1a2e; }

th {
    background-color: #1a1a2e;
    color: white;
    font-weight: 500;
    padding: 8px 10px;
    text-align: left;
    border: 1px solid #1a1a2e;
}

td { border: 1px solid #ddd; }

tr:nth-child(even) td { background-color: #f8f9fa; }

code {
    background: #f5f5f5;
    color: #c7254e;
}

pre {
    background: #2d2d2d;
    color: #f0f0f0;
}

pre code { color: #f0f0f0; }

strong { font-weight: 600; color: #1a1a2e; }
"""

CSS_SIMPLE = CSS_BASE + """
h1 {
    font-size: 14pt;
    font-weight: 700;
    color: #000;
    border-bottom: 1.5px solid #000;
    padding-bottom: 6px;
    margin-top: 28px;
    margin-bottom: 14px;
    page-break-after: avoid;
}

h1:first-child { margin-top: 0; }

h2 {
    font-size: 10pt;
    font-weight: 600;
    color: #000;
    border-bottom: 1px solid #ccc;
    padding-bottom: 4px;
    margin-top: 20px;
    margin-bottom: 10px;
    page-break-after: avoid;
}

h3 {
    font-size: 9pt;
    font-weight: 600;
    color: #000;
    margin-top: 16px;
    margin-bottom: 8px;
}

blockquote {
    border-left: 3px solid #ccc;
    background: #f5f5f5;
    margin: 12px 0;
    padding: 10px 16px;
    font-size: 7.5pt;
    color: #333;
}

th {
    background: none;
    color: #000;
    font-weight: 700;
    padding: 8px 10px;
    text-align: left;
    border: 1px solid #ccc;
}

td { border: 1px solid #ccc; }

tr:nth-child(even) td { background-color: #fafafa; }

code {
    background: #f5f5f5;
    color: #333;
}

pre {
    background: #f5f5f5;
    color: #333;
}

pre code { color: #333; }

strong { font-weight: 600; color: #000; }
"""

STYLES = {
    "navy": CSS_NAVY,
    "simple": CSS_SIMPLE,
}

MARKDOWN_EXTENSIONS = ["tables", "fenced_code", "codehilite", "toc", "pymdownx.tasklist"]
MARKDOWN_EXTENSION_CONFIGS = {
    "pymdownx.tasklist": {
        "custom_checkbox": True,
    },
}


def ensure_fonts():
    for path, url, name in [
        (NOTO_EMOJI_PATH, NOTO_EMOJI_URL, "NotoEmoji"),
        (D2CODING_PATH, D2CODING_URL, "D2Coding"),
    ]:
        if not os.path.exists(path):
            print(f"Downloading {name} font to {path}...", file=sys.stderr)
            urllib.request.urlretrieve(url, path)


def convert(md_path: str, pdf_path: str, style: str = "navy"):
    ensure_fonts()

    css = STYLES.get(style, CSS_NAVY)

    with open(md_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    html_body = markdown.markdown(
        md_content, extensions=MARKDOWN_EXTENSIONS,
        extension_configs=MARKDOWN_EXTENSION_CONFIGS,
    )

    # weasyprint can't render <input> properly — replace with unicode chars
    html_body = re.sub(
        r'<label class="task-list-control"><input type="checkbox" disabled checked/><span class="task-list-indicator"></span></label>',
        '\u2611 ', html_body)
    html_body = re.sub(
        r'<label class="task-list-control"><input type="checkbox" disabled/><span class="task-list-indicator"></span></label>',
        '\u2610 ', html_body)

    html_full = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
{css}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    HTML(string=html_full).write_pdf(pdf_path)
    print(f"PDF generated: {pdf_path} (style: {style})", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Convert Markdown to styled PDF")
    parser.add_argument("input", help="Input Markdown file path")
    parser.add_argument("output", help="Output PDF file path")
    parser.add_argument("--style", choices=["navy", "simple"], default="navy",
                        help="PDF style theme (default: navy)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    convert(args.input, args.output, style=args.style)


if __name__ == "__main__":
    main()
