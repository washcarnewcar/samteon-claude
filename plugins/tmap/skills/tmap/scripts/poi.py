#!/usr/bin/env python3
"""TMap POI 검색.

티맵 API의 얇은 래퍼. 서브커맨드 = 엔드포인트 1:1.

서브커맨드:
  search           POI 통합검색 (키워드)
                   GET /tmap/pois?version=1
  detail           POI 상세 (poiId)
                   GET /tmap/pois/{poiId}?version=1
  nearby-category  주변 카테고리 검색 (반경)
                   GET /tmap/pois/search/around?version=1
  around-route     경로 반경 POI 검색
                   POST /tmap/pois/search/aroundRoute?version=1
  admin-area       읍면동/도로명 조회
                   GET /tmap/pois/search/adminArea?version=1
  region-code      지역분류코드 검색
                   GET /tmap/pois/search/regionCode?version=1
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
    "search": "/tmap/pois",
    "nearby-category": "/tmap/pois/search/around",
    "around-route": "/tmap/poi/findPoiRoute",
    "admin-area": "/tmap/poi/findPoiAreaDataByName",
    "region-code": "/tmap/poi/areascode",
}


def add_common(p: argparse.ArgumentParser, cmd: str) -> None:
    p.add_argument("--json", dest="raw_json", help="raw JSON (query 또는 body) 병합")
    if cmd in DEFAULT_PATHS:
        p.add_argument("--path", default=DEFAULT_PATHS[cmd], help=f"엔드포인트 경로 (기본 {DEFAULT_PATHS[cmd]})")
    p.add_argument("--version", default="1", help="API version (기본 1)")
    p.add_argument("--format", default="json")
    p.add_argument("--output-full", metavar="PATH")
    p.add_argument("--pretty", action="store_true")
    p.add_argument(
        "--summarize",
        nargs="?",
        const="standard",
        choices=["minimal", "standard", "full"],
        help="POI 결과를 간단한 포맷으로 요약",
    )
    p.add_argument("--limit", type=int, default=None, help="요약 시 결과 개수 제한")


def run_search(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "searchKeyword": args.searchKeyword,
        "areaLLCode": args.areaLLCode,
        "areaLMCode": args.areaLMCode,
        "resCoordType": args.resCoordType,
        "reqCoordType": args.reqCoordType,
        "count": args.count,
        "page": args.page,
        "centerLat": args.centerLat,
        "centerLon": args.centerLon,
        "radius": args.radius,
        "searchType": args.searchType,
        "searchtypCd": args.searchtypCd,
        "multiPoint": args.multiPoint,
        "poiGroupYn": args.poiGroupYn,
    }
    execute_get(args, query, kind="poi")


def run_detail(args: argparse.Namespace) -> None:
    # path를 명시하지 않았으면 동적으로 /tmap/pois/{poiId} 구성
    path = args.path if args.path and args.path != "/tmap/pois" else f"/tmap/pois/{args.poiId}"
    query = {
        "version": args.version,
        "format": args.format,
        "resCoordType": args.resCoordType,
        "findOption": args.findOption,
        "callback": args.callback,
    }
    override = parse_json_body(args.raw_json)
    if override:
        query.update(override)
    client = TmapClient()
    resp = client.get(path, query=query)
    handle_output(resp, args, kind=None)


def run_nearby_category(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "centerLat": args.centerLat,
        "centerLon": args.centerLon,
        "radius": args.radius,
        "categories": args.categories,
        "resCoordType": args.resCoordType,
        "reqCoordType": args.reqCoordType,
        "count": args.count,
        "page": args.page,
    }
    execute_get(args, query, kind="poi")


def run_around_route(args: argparse.Namespace) -> None:
    # /tmap/poi/findPoiRoute 는 version을 body에 넣고 query는 비워둠
    body = {
        "version": args.version_body,
        "startX": args.startX,
        "startY": args.startY,
        "endX": args.endX,
        "endY": args.endY,
        "userX": args.userX,
        "userY": args.userY,
        "lineString": args.lineString,
        "searchType": args.searchTypeAR,
        "searchKeyword": args.searchKeyword,
        "radius": args.radius,
        "count": args.count,
        "page": args.page,
        "reqCoordType": args.reqCoordType,
        "resCoordType": args.resCoordType,
    }
    body = {k: v for k, v in body.items() if v is not None}
    override = parse_json_body(args.raw_json)
    body = merge_body(body, override)
    client = TmapClient()
    resp = client.post(args.path, body=body)
    handle_output(resp, args, kind="poi")


def run_admin_area(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "area_dong": args.area_dong,
        "area_si_do": args.area_si_do,
        "addressType": args.addressType,
        "resCoordType": args.resCoordType,
        "count": args.count,
        "page": args.page,
    }
    execute_get(args, query, kind=None)


def run_region_code(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "areaTypCd": args.areaTypCd,
        "largeCdFlag": args.largeCdFlag,
        "middleCdFlag": args.middleCdFlag,
        "smallCdFlag": args.smallCdFlag,
        "page": args.page,
        "count": args.count,
    }
    execute_get(args, query, kind=None)


def execute_get(args: argparse.Namespace, query: dict, *, kind: str | None) -> None:
    override = parse_json_body(args.raw_json)
    if override:
        query.update(override)
    client = TmapClient()
    resp = client.get(args.path, query=query)
    handle_output(resp, args, kind=kind)


def handle_output(resp, args: argparse.Namespace, *, kind: str | None) -> None:
    if args.output_full:
        Path(args.output_full).write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    data = resp
    if args.summarize and kind == "poi":
        data = apply_summarize(resp, kind="poi", level=args.summarize, extra={"limit": args.limit})
    output_json(data, pretty=args.pretty)


def main() -> int:
    parser = argparse.ArgumentParser(prog="poi.py", description="TMap POI 검색 얇은 래퍼")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="POI 통합검색")
    add_common(p, "search")
    p.add_argument("--keyword", "--searchKeyword", dest="searchKeyword", required=True, help="검색 키워드")
    p.add_argument("--area-ll", "--areaLLCode", dest="areaLLCode", help="대분류 지역 코드")
    p.add_argument("--area-lm", "--areaLMCode", dest="areaLMCode", help="중분류 지역 코드")
    p.add_argument("--req-coord-type", "--reqCoordType", dest="reqCoordType", default="WGS84GEO")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.add_argument("--count", type=int, help="결과 개수 (기본 20, 최대 200)")
    p.add_argument("--page", type=int, help="페이지 번호")
    p.add_argument("--center-lat", "--centerLat", dest="centerLat", help="중심 위도")
    p.add_argument("--center-lon", "--centerLon", dest="centerLon", help="중심 경도")
    p.add_argument("--radius", help="반경 (km)")
    p.add_argument("--search-type", "--searchType", dest="searchType", help="검색 유형")
    p.add_argument("--search-typ-cd", "--searchtypCd", dest="searchtypCd", help="검색 유형 코드")
    p.add_argument("--multi-point", "--multiPoint", dest="multiPoint", help="다중 포인트 플래그")
    p.add_argument("--poi-group-yn", "--poiGroupYn", dest="poiGroupYn", help="POI 그룹 여부")
    p.set_defaults(func=run_search)

    p = sub.add_parser("detail", help="POI 상세 조회 (GET /tmap/pois/{poiId})")
    p.add_argument("--json", dest="raw_json")
    p.add_argument("--path", default=None, help="엔드포인트 경로 (기본 /tmap/pois/{poiId})")
    p.add_argument("--version", default="1")
    p.add_argument("--format", default="json")
    p.add_argument("--output-full", metavar="PATH")
    p.add_argument("--pretty", action="store_true")
    p.add_argument("--summarize", nargs="?", const="standard", choices=["minimal", "standard", "full"])
    p.add_argument("--limit", type=int)
    p.add_argument("--poi-id", "--poiId", dest="poiId", required=True, help="POI ID")
    p.add_argument("--find-option", "--findOption", dest="findOption", help="조회 옵션")
    p.add_argument("--callback", help="JSONP 콜백")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.set_defaults(func=run_detail)

    p = sub.add_parser("nearby-category", help="주변 카테고리 POI 검색")
    add_common(p, "nearby-category")
    p.add_argument("--center-lat", "--centerLat", dest="centerLat", required=True)
    p.add_argument("--center-lon", "--centerLon", dest="centerLon", required=True)
    p.add_argument("--radius", required=True, help="반경 (km)")
    p.add_argument("--categories", required=True, help="카테고리 코드 (콤마 구분)")
    p.add_argument("--req-coord-type", "--reqCoordType", dest="reqCoordType", default="WGS84GEO")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.add_argument("--count", type=int)
    p.add_argument("--page", type=int)
    p.set_defaults(func=run_nearby_category)

    p = sub.add_parser("around-route", help="경로 반경 POI 검색 (POST /tmap/poi/findPoiRoute)")
    add_common(p, "around-route")
    p.add_argument("--version-body", default="1.0", help="body에 넣는 version 값 (기본 '1.0')")
    p.add_argument("--start-x", "--startX", dest="startX", required=True)
    p.add_argument("--start-y", "--startY", dest="startY", required=True)
    p.add_argument("--end-x", "--endX", dest="endX", required=True)
    p.add_argument("--end-y", "--endY", dest="endY", required=True)
    p.add_argument("--user-x", "--userX", dest="userX", help="사용자 현재 경도")
    p.add_argument("--user-y", "--userY", dest="userY", help="사용자 현재 위도")
    p.add_argument("--line-string", "--lineString", dest="lineString", help="경로 좌표열 '경도,위도_경도,위도...' 형식")
    p.add_argument(
        "--search-type-ar",
        "--searchType",
        dest="searchTypeAR",
        choices=["keyword", "category", "around"],
        default="keyword",
    )
    p.add_argument("--keyword", "--searchKeyword", dest="searchKeyword", help="검색 키워드")
    p.add_argument("--radius", type=int, help="반경 (km)")
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--req-coord-type", "--reqCoordType", dest="reqCoordType", default="WGS84GEO")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.set_defaults(func=run_around_route)

    p = sub.add_parser("admin-area", help="읍면동/도로명 조회")
    add_common(p, "admin-area")
    p.add_argument(
        "--area-dong",
        "--area_dong",
        dest="area_dong",
        required=True,
        help="읍/면/동/리 또는 도로명 (예: '합정동', '세솔로')",
    )
    p.add_argument("--area-si-do", "--area_si_do", dest="area_si_do", help="시/도 (선택)")
    p.add_argument(
        "--address-type",
        "--addressType",
        dest="addressType",
        choices=["addressName", "roadName", "all"],
        help="주소 유형 필터",
    )
    p.add_argument("--count", type=int, default=10, help="페이지당 결과 (1~200, 기본 10)")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.set_defaults(func=run_admin_area)

    p = sub.add_parser("region-code", help="지역분류코드 검색")
    add_common(p, "region-code")
    p.add_argument(
        "--area-typ-cd",
        "--areaTypCd",
        dest="areaTypCd",
        default="01",
        choices=["01", "02"],
        help="지역 유형 (01=행정, 02=법정, 기본 01)",
    )
    p.add_argument("--large-cd-flag", "--largeCdFlag", dest="largeCdFlag", default="Y", choices=["Y", "N"])
    p.add_argument("--middle-cd-flag", "--middleCdFlag", dest="middleCdFlag", default="N", choices=["Y", "N"])
    p.add_argument("--small-cd-flag", "--smallCdFlag", dest="smallCdFlag", default="N", choices=["Y", "N"])
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--count", type=int, default=10, help="페이지당 결과 (10~8000, 기본 10)")
    p.set_defaults(func=run_region_code)

    args = parser.parse_args()
    # detail 서브커맨드는 path 기본값이 동적이므로 수동 처리
    if args.cmd == "detail" and not hasattr(args, "path"):
        args.path = None
    try:
        args.func(args)
    except Exception as e:
        handle_error_and_exit(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
