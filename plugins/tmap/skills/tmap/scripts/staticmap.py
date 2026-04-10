#!/usr/bin/env python3
"""TMap Static Map 이미지 생성.

서브커맨드:
  render  정적 지도 이미지 렌더링
          GET /tmap/staticMap?version=1

공식 필수 파라미터: longitude, latitude, zoom (기본 15)
선택: width/height (1~512, 기본 512), format (PNG/JPG, 기본 PNG), markers, coordType

공식 문서: https://skopenapi.readme.io/reference/staticmap
응답: 바이너리 이미지. --output <path>가 필수.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tmap_client import (
    TmapClient,
    handle_error_and_exit,
    output_json,
    parse_json_body,
)

DEFAULT_PATH = "/tmap/staticMap"


def main() -> int:
    parser = argparse.ArgumentParser(prog="staticmap.py", description="TMap Static Map 얇은 래퍼")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("render", help="정적 지도 이미지 렌더링")
    p.add_argument("--json", dest="raw_json")
    p.add_argument("--path", default=DEFAULT_PATH)
    p.add_argument("--version", default="1")
    p.add_argument("--output", required=True, help="이미지 저장 경로 (PNG/JPG)")
    p.add_argument("--latitude", required=True, help="중심 위도")
    p.add_argument("--longitude", required=True, help="중심 경도")
    p.add_argument("--zoom", type=int, default=15, help="줌 레벨 (6~19, 기본 15)")
    p.add_argument("--width", type=int, default=512, help="이미지 너비 px (1~512, 기본 512)")
    p.add_argument("--height", type=int, default=512, help="이미지 높이 px (1~512, 기본 512)")
    p.add_argument("--format", default="PNG", choices=["PNG", "JPG", "png", "jpg"], help="PNG 또는 JPG")
    p.add_argument("--markers", help="마커 좌표 (예: 126.978155,37.566371)")
    p.add_argument("--coord-type", "--coordType", dest="coordType", default="WGS84GEO")

    args = parser.parse_args()
    fmt = args.format.upper()
    query = {
        "version": args.version,
        "longitude": args.longitude,
        "latitude": args.latitude,
        "zoom": args.zoom,
        "width": args.width,
        "height": args.height,
        "format": fmt,
        "markers": args.markers,
        "coordType": args.coordType,
    }
    override = parse_json_body(args.raw_json)
    if override:
        query.update(override)
    try:
        client = TmapClient()
        content = client.request("GET", args.path, query=query, accept=f"image/{fmt.lower()}")
        if isinstance(content, (dict, list)):
            print(f"예상치 못한 JSON 응답: {content}", file=sys.stderr)
            return 4
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        output_json({"savedTo": str(out.resolve()), "bytes": len(content)})
    except Exception as e:
        handle_error_and_exit(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
