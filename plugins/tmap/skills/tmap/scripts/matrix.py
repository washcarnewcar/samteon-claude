#!/usr/bin/env python3
"""TMap 경로 매트릭스 (다중 Origin/Destination 시간·거리).

서브커맨드:
  od   다중 O/D 시간·거리 계산
       POST /tmap/matrix?version=1
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

DEFAULT_PATH = "/tmap/matrix"


def main() -> int:
    parser = argparse.ArgumentParser(prog="matrix.py", description="TMap 경로 매트릭스 얇은 래퍼")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("od", help="다중 Origin/Destination 매트릭스")
    p.add_argument("--json", dest="raw_json")
    p.add_argument("--path", default=DEFAULT_PATH)
    p.add_argument("--version", default="1")
    p.add_argument("--output-full", metavar="PATH")
    p.add_argument("--pretty", action="store_true")
    p.add_argument(
        "--summarize",
        nargs="?",
        const="standard",
        choices=["minimal", "standard", "full"],
        help="매트릭스를 표 형태로 요약",
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--origins-json", help="출발지 배열 JSON (각 항목: {lat, lon} 또는 티맵 스키마)")
    group.add_argument("--origins-file", help="출발지 배열 JSON 파일")
    group2 = p.add_mutually_exclusive_group(required=True)
    group2.add_argument("--destinations-json", help="목적지 배열 JSON")
    group2.add_argument("--destinations-file", help="목적지 배열 JSON 파일")
    p.add_argument("--req-coord-type", "--reqCoordType", dest="reqCoordType", default="WGS84GEO")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.add_argument("--search-option", "--searchOption", dest="searchOption")
    p.add_argument("--traffic-info", "--trafficInfo", dest="trafficInfo", choices=["Y", "N"])

    args = parser.parse_args()
    try:
        origins = _load_list(args.origins_json, args.origins_file, "origins")
        destinations = _load_list(args.destinations_json, args.destinations_file, "destinations")
        body = {
            "origins": origins,
            "destinations": destinations,
            "reqCoordType": args.reqCoordType,
            "resCoordType": args.resCoordType,
            "searchOption": args.searchOption,
            "trafficInfo": args.trafficInfo,
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
            data = apply_summarize(resp, kind="matrix", level=args.summarize)
        output_json(data, pretty=args.pretty)
    except Exception as e:
        handle_error_and_exit(e)
    return 0


def _load_list(raw: str | None, file: str | None, label: str) -> list:
    if raw is None and file:
        raw = Path(file).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"{label} JSON 파싱 실패: {e}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, list):
        print(f"{label}는 JSON 배열이어야 합니다.", file=sys.stderr)
        sys.exit(2)
    return data


if __name__ == "__main__":
    sys.exit(main())
