#!/usr/bin/env python3
"""TMap 경유지 경로 및 경유지 최적화.

티맵 API의 얇은 래퍼. 서브커맨드 = 엔드포인트 1:1.

서브커맨드:
  multi-30      다중 경유지 경로 (30개)
                POST /tmap/routes/routeSequential30?version=1
  multi-100     다중 경유지 경로 (100개)
                POST /tmap/routes/routeSequential100?version=1
  multi-200     다중 경유지 경로 (200개)
                POST /tmap/routes/routeSequential200?version=1
  optimize-10   경유지 방문 순서 최적화 (10개)
                POST /tmap/routes/routeOptimization10?version=1
  optimize-20   경유지 방문 순서 최적화 (20개)
                POST /tmap/routes/routeOptimization20?version=1
  optimize-30   경유지 방문 순서 최적화 (30개)
                POST /tmap/routes/routeOptimization30?version=1
  optimize-100  경유지 방문 순서 최적화 (100개)
                POST /tmap/routes/routeOptimization100?version=1

경유지 리스트는 --stops-json '[{...},{...}]' 또는 --stops-file <path> 로 전달합니다.
각 경유지 객체의 키는 티맵 API의 viaPoints 요소 구조를 그대로 사용합니다
(viaPointId, viaPointName, viaX, viaY, viaPointDetailAddress 등).
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
    "multi-30": "/tmap/routes/routeSequential30",
    "multi-100": "/tmap/routes/routeSequential100",
    "multi-200": "/tmap/routes/routeSequential200",
    "optimize-10": "/tmap/routes/routeOptimization10",
    "optimize-20": "/tmap/routes/routeOptimization20",
    "optimize-30": "/tmap/routes/routeOptimization30",
    "optimize-100": "/tmap/routes/routeOptimization100",
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
        help="경로 응답 요약",
    )
    p.add_argument("--turns", type=int, default=None)


def add_waypoint_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--start-name", "--startName", dest="startName", help="출발지 이름")
    p.add_argument("--start-x", "--startX", dest="startX", required=True, help="출발 경도")
    p.add_argument("--start-y", "--startY", dest="startY", required=True, help="출발 위도")
    p.add_argument("--start-time", "--startTime", dest="startTime", help="출발 시각 (YYYYMMDDHHmm)")
    p.add_argument("--end-name", "--endName", dest="endName", help="도착지 이름")
    p.add_argument("--end-x", "--endX", dest="endX", required=True, help="도착 경도")
    p.add_argument("--end-y", "--endY", dest="endY", required=True, help="도착 위도")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--stops-json", help="경유지 배열 JSON (viaPoints 스키마)")
    group.add_argument("--stops-file", help="경유지 배열 JSON 파일 경로")
    p.add_argument("--req-coord-type", "--reqCoordType", dest="reqCoordType", default="WGS84GEO")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.add_argument("--search-option", "--searchOption", dest="searchOption")
    p.add_argument("--car-type", "--carType", dest="carType")


def load_stops(args: argparse.Namespace) -> list:
    raw = args.stops_json
    if raw is None and args.stops_file:
        raw = Path(args.stops_file).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"stops JSON 파싱 실패: {e}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, list):
        print("stops는 JSON 배열이어야 합니다.", file=sys.stderr)
        sys.exit(2)
    return data


def run(args: argparse.Namespace) -> None:
    stops = load_stops(args)
    body = {
        "reqCoordType": args.reqCoordType,
        "resCoordType": args.resCoordType,
        "startName": args.startName,
        "startX": args.startX,
        "startY": args.startY,
        "startTime": args.startTime,
        "endName": args.endName,
        "endX": args.endX,
        "endY": args.endY,
        "viaPoints": stops,
        "searchOption": args.searchOption,
        "carType": args.carType,
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
        data = apply_summarize(resp, kind="route", level=args.summarize, extra={"turns": args.turns})
    output_json(data, pretty=args.pretty)


def main() -> int:
    parser = argparse.ArgumentParser(prog="waypoints.py", description="TMap 경유지 경로 얇은 래퍼")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for cmd in DEFAULT_PATHS.keys():
        kind = "다중 경유지 경로" if cmd.startswith("multi") else "경유지 방문 순서 최적화"
        count = cmd.split("-")[-1]
        p = sub.add_parser(cmd, help=f"{kind} ({count}개)")
        add_common(p, cmd)
        add_waypoint_args(p)
        p.set_defaults(func=run)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        handle_error_and_exit(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
