#!/usr/bin/env python3
"""TMap 실시간 교통정보.

서브커맨드:
  live  실시간 교통정보 조회
        GET /tmap/traffic?version=1

공식 파라미터 (선택적, 기본값 있음):
- bbox 방식: minLat, minLon, maxLat, maxLon
- 중심+반경 방식: centerLat, centerLon, radius (1~9, 300m~2700m 단위)
- zoomLevel (1~19, 기본 7)
- trafficType: AUTO / AROUND / POINT / ACC (기본 null=전체)
- reqCoordType, resCoordType, sort, callback

공식 문서: https://skopenapi.readme.io/reference/교통정보-1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tmap_client import (
    TmapClient,
    handle_error_and_exit,
    output_json,
    parse_json_body,
)

DEFAULT_PATH = "/tmap/traffic"


def main() -> int:
    parser = argparse.ArgumentParser(prog="traffic.py", description="TMap 실시간 교통정보 얇은 래퍼")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("live", help="실시간 교통정보")
    p.add_argument("--json", dest="raw_json")
    p.add_argument("--path", default=DEFAULT_PATH)
    p.add_argument("--version", default="1")
    # bbox 방식
    p.add_argument("--min-lat", "--minLat", dest="minLat", help="사각 범위 최소 위도")
    p.add_argument("--min-lon", "--minLon", dest="minLon", help="사각 범위 최소 경도")
    p.add_argument("--max-lat", "--maxLat", dest="maxLat", help="사각 범위 최대 위도")
    p.add_argument("--max-lon", "--maxLon", dest="maxLon", help="사각 범위 최대 경도")
    # 중심 + 반경 방식
    p.add_argument("--center-lat", "--centerLat", dest="centerLat", help="중심 위도")
    p.add_argument("--center-lon", "--centerLon", dest="centerLon", help="중심 경도")
    p.add_argument(
        "--radius",
        type=int,
        help="반경 (1~9, 300m~2700m 단위. km 아님!)",
    )
    p.add_argument(
        "--traffic-type",
        "--trafficType",
        dest="trafficType",
        choices=["AUTO", "AROUND", "POINT", "ACC"],
        help="교통 유형 (AUTO/AROUND/POINT/ACC). 미지정 시 전체",
    )
    p.add_argument("--zoom-level", "--zoomLevel", dest="zoomLevel", type=int, help="줌 레벨 (1~19, 기본 7)")
    p.add_argument("--sort", help="정렬 방식 (기본 index)")
    p.add_argument("--req-coord-type", "--reqCoordType", dest="reqCoordType")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType")
    p.add_argument("--callback", help="JSONP 콜백")
    p.add_argument("--output-full", metavar="PATH")
    p.add_argument("--pretty", action="store_true")

    args = parser.parse_args()
    query = {
        "version": args.version,
        "minLat": args.minLat,
        "minLon": args.minLon,
        "maxLat": args.maxLat,
        "maxLon": args.maxLon,
        "centerLat": args.centerLat,
        "centerLon": args.centerLon,
        "radius": args.radius,
        "trafficType": args.trafficType,
        "zoomLevel": args.zoomLevel,
        "sort": args.sort,
        "reqCoordType": args.reqCoordType,
        "resCoordType": args.resCoordType,
        "callback": args.callback,
    }
    override = parse_json_body(args.raw_json)
    if override:
        query.update(override)
    try:
        client = TmapClient()
        resp = client.get(args.path, query=query)
        if args.output_full:
            Path(args.output_full).write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
        output_json(resp, pretty=args.pretty)
    except Exception as e:
        handle_error_and_exit(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
