#!/usr/bin/env python3
"""Markdown to PDF converter - Simple (B&W) style wrapper."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from md2pdf import convert


def main():
    parser = argparse.ArgumentParser(description="Convert Markdown to simple B&W PDF")
    parser.add_argument("input", help="Input Markdown file path")
    parser.add_argument("output", help="Output PDF file path")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    convert(args.input, args.output, style="simple")


if __name__ == "__main__":
    main()
