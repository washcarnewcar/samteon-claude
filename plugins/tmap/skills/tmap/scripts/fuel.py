#!/usr/bin/env python3
"""TMap 유가정보 (주유소·전기차 충전소).

유가정보는 별도 엔드포인트가 아니라 **POI 주변 카테고리 검색 API의 특수 케이스**입니다.
`/tmap/pois/search/around` 엔드포인트에 categories="주유소" 또는 dataKind 필터로 조회.

서브커맨드:
  nearby  주변 주유소/충전소 검색
          GET /tmap/pois/search/around?version=1
          - categories=주유소 또는 dataKind=3 (주유소) / dataKind=6 (전기차 충전소)
  detail  POI ID로 상세 조회
          GET /tmap/pois/{poiId}?version=1 (POI 상세 API 재사용)

참고: `/tmap/puzzle/pois` 엔드포인트는 존재하지 않습니다.
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

DEFAULT_PATHS = {
    "nearby": "/tmap/pois/search/around",
}


def run_nearby(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "centerLat": args.centerLat,
        "centerLon": args.centerLon,
        "radius": args.radius,
        "categories": args.categories,
        "dataKind": args.dataKind,
        "brandName": args.brandName,
        "reqCoordType": args.reqCoordType,
        "resCoordType": args.resCoordType,
        "count": args.count,
        "page": args.page,
        "sort": args.sort,
    }
    override = parse_json_body(args.raw_json)
    if override:
        query.update(override)
    client = TmapClient()
    resp = client.get(args.path, query=query)
    emit(resp, args)


def run_detail(args: argparse.Namespace) -> None:
    path = args.path or f"/tmap/pois/{args.poiId}"
    query = {
        "version": args.version,
        "format": args.format,
        "resCoordType": args.resCoordType,
    }
    override = parse_json_body(args.raw_json)
    if override:
        query.update(override)
    client = TmapClient()
    resp = client.get(path, query=query)
    emit(resp, args)


def emit(resp, args: argparse.Namespace) -> None:
    if args.output_full:
        Path(args.output_full).write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    output_json(resp, pretty=args.pretty)


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", dest="raw_json")
    p.add_argument("--version", default="1")
    p.add_argument("--format", default="json")
    p.add_argument("--output-full", metavar="PATH")
    p.add_argument("--pretty", action="store_true")


def main() -> int:
    parser = argparse.ArgumentParser(prog="fuel.py", description="TMap 유가정보 얇은 래퍼 (POI around 재사용)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("nearby", help="주변 주유소/충전소 검색")
    add_common(p)
    p.add_argument("--path", default=DEFAULT_PATHS["nearby"])
    p.add_argument("--center-lat", "--centerLat", dest="centerLat", required=True)
    p.add_argument("--center-lon", "--centerLon", dest="centerLon", required=True)
    p.add_argument("--radius", required=True, help="반경 (km)")
    p.add_argument(
        "--categories",
        default="주유소",
        help="카테고리 (기본 '주유소'. 전기차는 '전기차충전소')",
    )
    p.add_argument("--data-kind", "--dataKind", dest="dataKind", help="데이터 종류 필터 (3=주유소, 6=전기차 충전소)")
    p.add_argument("--brand-name", "--brandName", dest="brandName", help="브랜드명 필터")
    p.add_argument("--req-coord-type", "--reqCoordType", dest="reqCoordType", default="WGS84GEO")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.add_argument("--count", type=int)
    p.add_argument("--page", type=int)
    p.add_argument("--sort", help="정렬 기준 (price, distance 등)")
    p.set_defaults(func=run_nearby)

    p = sub.add_parser("detail", help="POI 상세 (POI API 재사용)")
    add_common(p)
    p.add_argument("--path", default=None, help="엔드포인트 경로 (기본 /tmap/pois/{poiId})")
    p.add_argument("--poi-id", "--poiId", dest="poiId", required=True)
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.set_defaults(func=run_detail)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        handle_error_and_exit(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
