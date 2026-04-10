#!/usr/bin/env python3
"""TMap 대중교통 경로안내.

티맵 API의 얇은 래퍼. 서브커맨드 = 엔드포인트 1:1.

서브커맨드:
  route    대중교통 경로안내 (상세)
           POST /transit/routes?version=1
  summary  대중교통 경로 요약
           POST /transit/routes/sub?version=1

버스/지하철/기차/항공/해운 통합 경로를 지원합니다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tmap_client import (
    TmapClient,
    apply_summarize,
    handle_error_and_exit,
    merge_body,
    output_json,
    parse_json_body,
)

DEFAULT_PATHS = {
    "route": "/transit/routes",
    "summary": "/transit/routes/sub",
}


def add_common(p: argparse.ArgumentParser, cmd: str) -> None:
    p.add_argument("--json", dest="raw_json", help="raw JSON 바디 병합")
    p.add_argument("--path", default=DEFAULT_PATHS[cmd], help=f"엔드포인트 경로 (기본 {DEFAULT_PATHS[cmd]})")
    p.add_argument("--version", default="1")
    p.add_argument("--output-full", metavar="PATH")
    p.add_argument("--pretty", action="store_true")
    p.add_argument(
        "--summarize",
        nargs="?",
        const="standard",
        choices=["minimal", "standard", "full"],
        help="경로 옵션을 간단히 요약",
    )
    p.add_argument("--options", type=int, default=None, help="요약 시 반환할 경로 옵션 개수")


def add_transit_body_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--start-x", "--startX", dest="startX", required=True, help="출발 경도")
    p.add_argument("--start-y", "--startY", dest="startY", required=True, help="출발 위도")
    p.add_argument("--end-x", "--endX", dest="endX", required=True, help="도착 경도")
    p.add_argument("--end-y", "--endY", dest="endY", required=True, help="도착 위도")
    p.add_argument("--lang", type=int, choices=[0, 1], help="0 한국어, 1 영어")
    p.add_argument("--format", default="json")
    p.add_argument("--count", type=int, help="경로 옵션 개수")
    p.add_argument("--search-dttm", "--searchDttm", dest="searchDttm", help="검색 일시 (YYYYMMDDHHmm)")


def run_route(args: argparse.Namespace) -> None:
    _run(args)


def run_summary(args: argparse.Namespace) -> None:
    _run(args)


def _run(args: argparse.Namespace) -> None:
    body = {
        "startX": args.startX,
        "startY": args.startY,
        "endX": args.endX,
        "endY": args.endY,
        "lang": args.lang,
        "format": args.format,
        "count": args.count,
        "searchDttm": args.searchDttm,
    }
    body = {k: v for k, v in body.items() if v is not None}
    override = parse_json_body(args.raw_json)
    body = merge_body(body, override)
    client = TmapClient()
    resp = client.post(args.path, body=body, query={"version": args.version})
    if args.output_full:
        Path(args.output_full).write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    data = resp
    if args.summarize:
        data = apply_summarize(resp, kind="transit", level=args.summarize, extra={"options": args.options})
    output_json(data, pretty=args.pretty)


def main() -> int:
    parser = argparse.ArgumentParser(prog="transit.py", description="TMap 대중교통 경로 얇은 래퍼")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("route", help="대중교통 경로안내 (상세)")
    add_common(p, "route")
    add_transit_body_args(p)
    p.set_defaults(func=run_route)

    p = sub.add_parser("summary", help="대중교통 경로 요약")
    add_common(p, "summary")
    add_transit_body_args(p)
    p.set_defaults(func=run_summary)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        handle_error_and_exit(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
