#!/usr/bin/env python3
"""TMap 지오펜싱 (공간검색 및 영역조회).

서브커맨드:
  spatial-search  공간 검색 (키워드 또는 좌표로 행정구역 영역 검색)
                  GET /tmap/geofencing/regions?version=1
  area            영역 상세 조회 (regionId path 파라미터)
                  GET /tmap/geofencing/regions/{regionId}?version=1

공식 문서:
- https://skopenapi.readme.io/reference/공간검색-api
- https://skopenapi.readme.io/reference/영역조회-api

spatial-search 필수: count, categories, searchType (KEYWORD|COORDINATES)
  - searchType=KEYWORD → searchKeyword 필수
  - searchType=COORDINATES → reqLon, reqLat 필수
categories 값: city_do, gu_gun, legalDong, adminDong
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

DEFAULT_SPATIAL_PATH = "/tmap/geofencing/regions"


def run_spatial_search(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "count": args.count,
        "page": args.page,
        "categories": args.categories,
        "searchType": args.searchType,
        "searchKeyword": args.searchKeyword,
        "reqLon": args.reqLon,
        "reqLat": args.reqLat,
        "reqCoordType": args.reqCoordType,
        "resCoordType": args.resCoordType,
    }
    _execute(args, query)


def run_area(args: argparse.Namespace) -> None:
    path = args.path or f"/tmap/geofencing/regions/{args.regionId}"
    query = {
        "version": args.version,
        "resCoordType": args.resCoordType,
    }
    override = parse_json_body(args.raw_json)
    if override:
        query.update(override)
    client = TmapClient()
    resp = client.get(path, query=query)
    _emit(resp, args)


def _execute(args: argparse.Namespace, query: dict) -> None:
    override = parse_json_body(args.raw_json)
    if override:
        query.update(override)
    client = TmapClient()
    resp = client.get(args.path, query=query)
    _emit(resp, args)


def _emit(resp, args: argparse.Namespace) -> None:
    if args.output_full:
        Path(args.output_full).write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    output_json(resp, pretty=args.pretty)


def main() -> int:
    parser = argparse.ArgumentParser(prog="geofence.py", description="TMap 지오펜싱 얇은 래퍼")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("spatial-search", help="공간 검색 (행정구역)")
    p.add_argument("--json", dest="raw_json")
    p.add_argument("--path", default=DEFAULT_SPATIAL_PATH)
    p.add_argument("--version", default="1")
    p.add_argument("--output-full", metavar="PATH")
    p.add_argument("--pretty", action="store_true")
    p.add_argument("--count", type=int, default=20, help="페이지당 결과 수 (1~200, 기본 20)")
    p.add_argument("--page", type=int, default=1)
    p.add_argument(
        "--categories",
        required=True,
        choices=["city_do", "gu_gun", "legalDong", "adminDong"],
        help="검색 카테고리",
    )
    p.add_argument(
        "--search-type",
        "--searchType",
        dest="searchType",
        required=True,
        choices=["KEYWORD", "COORDINATES"],
        help="검색 방법",
    )
    p.add_argument("--search-keyword", "--searchKeyword", dest="searchKeyword", help="searchType=KEYWORD 시 필수")
    p.add_argument("--req-lon", "--reqLon", dest="reqLon", help="searchType=COORDINATES 시 필수")
    p.add_argument("--req-lat", "--reqLat", dest="reqLat", help="searchType=COORDINATES 시 필수")
    p.add_argument("--req-coord-type", "--reqCoordType", dest="reqCoordType", default="WGS84GEO")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.set_defaults(func=run_spatial_search)

    p = sub.add_parser("area", help="영역 상세 조회 (regionId)")
    p.add_argument("--json", dest="raw_json")
    p.add_argument("--path", default=None, help="엔드포인트 경로 (기본 /tmap/geofencing/regions/{regionId})")
    p.add_argument("--version", default="1")
    p.add_argument("--output-full", metavar="PATH")
    p.add_argument("--pretty", action="store_true")
    p.add_argument("--region-id", "--regionId", dest="regionId", required=True, help="공간검색에서 얻은 ID")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.set_defaults(func=run_area)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        handle_error_and_exit(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
