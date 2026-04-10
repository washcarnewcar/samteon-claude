#!/usr/bin/env python3
"""TMap 지오코딩 및 좌표/주소 변환.

티맵 API의 얇은 래퍼. 서브커맨드 = 엔드포인트 1:1.

서브커맨드:
  forward        순방향 지오코딩 (시도/구/동 분리 → 좌표)
                 GET /tmap/geo/geocoding?version=1
  full           전문자 지오코딩 (전체 주소 → 좌표)
                 GET /tmap/geo/fullAddrGeo?version=1
  reverse        역지오코딩 (좌표 → 주소)
                 GET /tmap/geo/reversegeocoding?version=1
  convert        좌표계 변환
                 GET /tmap/geo/coordconvert?version=1
  address        주소 변환 (지번↔도로명)
                 GET /tmap/geo/addressinfo?version=1
  near-road      좌표→근처 도로 매칭
                 GET /tmap/geo/nearroad?version=1
  postal         주소→우편번호
                 GET /tmap/geo/postcode?version=1
  reverse-label  좌표→지역레이블
                 GET /tmap/geo/reverseLabel?version=1

엔드포인트 경로가 달라지면 --path 옵션으로 덮어쓸 수 있습니다.
응답 포맷/파라미터 추가 변경이 있으면 --json으로 raw query dict를 병합할 수 있습니다.
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
    "forward": "/tmap/geo/geocoding",
    "full": "/tmap/geo/fullAddrGeo",
    "reverse": "/tmap/geo/reversegeocoding",
    "convert": "/tmap/geo/coordconvert",
    "address": "/tmap/geo/convertAddress",
    "near-road": "/tmap/road/nearToRoad",
    "postal": "/tmap/geo/postcode",
    "reverse-label": "/tmap/geo/reverseLabel",
}


def add_common(p: argparse.ArgumentParser, cmd: str) -> None:
    p.add_argument("--json", dest="raw_json", help="raw JSON 쿼리 파라미터를 직접 병합")
    p.add_argument("--path", default=DEFAULT_PATHS[cmd], help=f"엔드포인트 경로 (기본 {DEFAULT_PATHS[cmd]})")
    p.add_argument("--version", default="1", help="API version (기본 1)")
    p.add_argument("--output-full", metavar="PATH", help="전체 원본 응답을 파일에 저장")
    p.add_argument("--pretty", action="store_true", help="stdout JSON 들여쓰기")
    p.add_argument("--format", default="json", help="응답 포맷 (기본 json)")
    p.add_argument(
        "--coord-type",
        "--coordType",
        dest="coordType",
        default="WGS84GEO",
        help="좌표계 (기본 WGS84GEO)",
    )


def run_forward(args: argparse.Namespace) -> None:
    """시도/구/동 분리 주소로 지오코딩."""
    query = {
        "version": args.version,
        "format": args.format,
        "coordType": args.coordType,
        "city_do": args.city_do,
        "gu_gun": args.gu_gun,
        "dong": args.dong,
        "bunji": args.bunji,
        "addressFlag": args.addressFlag,
    }
    execute_get(args, query)


def run_full(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "coordType": args.coordType,
        "fullAddr": args.fullAddr,
    }
    execute_get(args, query)


def run_reverse(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "coordType": args.coordType,
        "lat": args.lat,
        "lon": args.lon,
        "addressType": args.addressType,
    }
    execute_get(args, query)


def run_convert(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "fromCoord": args.fromCoord,
        "toCoord": args.toCoord,
        "lat": args.lat,
        "lon": args.lon,
    }
    execute_get(args, query)


def run_address(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "searchTypCd": args.searchTypCd,
        "reqAdd": args.reqAdd,
        "reqMulti": args.reqMulti,
        "resCoordType": args.resCoordType,
    }
    execute_get(args, query)


def run_near_road(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "coordType": args.coordType,
        "lat": args.lat,
        "lon": args.lon,
    }
    execute_get(args, query)


def run_postal(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "addr": args.addr,
        "addressFlag": args.addressFlag,
        "coordType": args.coordType,
        "page": args.page,
        "count": args.count,
    }
    execute_get(args, query)


def run_reverse_label(args: argparse.Namespace) -> None:
    query = {
        "version": args.version,
        "format": args.format,
        "centerLat": args.centerLat,
        "centerLon": args.centerLon,
        "reqLevel": args.reqLevel,
        "reqCoordType": args.reqCoordType,
        "resCoordType": args.resCoordType,
    }
    execute_get(args, query)


def execute_get(args: argparse.Namespace, query: dict) -> None:
    override = parse_json_body(args.raw_json)
    if override:
        query.update(override)
    client = TmapClient()
    resp = client.get(args.path, query=query)
    if args.output_full:
        Path(args.output_full).write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    output_json(resp, pretty=args.pretty)


def main() -> int:
    parser = argparse.ArgumentParser(prog="geocode.py", description="TMap 지오코딩 얇은 래퍼")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("forward", help="순방향 지오코딩 (시도/구/동 분리)")
    add_common(p, "forward")
    p.add_argument("--city-do", "--city_do", dest="city_do", help="시/도")
    p.add_argument("--gu-gun", "--gu_gun", dest="gu_gun", help="구/군")
    p.add_argument("--dong", help="동/읍/면")
    p.add_argument("--bunji", help="지번")
    p.add_argument("--address-flag", "--addressFlag", dest="addressFlag", help="주소 유형 플래그")
    p.set_defaults(func=run_forward)

    p = sub.add_parser("full", help="전문자 지오코딩 (전체 주소 문자열)")
    add_common(p, "full")
    p.add_argument("--full-addr", "--fullAddr", dest="fullAddr", required=True, help="전체 주소 문자열")
    p.set_defaults(func=run_full)

    p = sub.add_parser("reverse", help="역지오코딩 (좌표 → 주소)")
    add_common(p, "reverse")
    p.add_argument("--lat", required=True, help="위도")
    p.add_argument("--lon", required=True, help="경도")
    p.add_argument("--address-type", "--addressType", dest="addressType", help="주소 유형 (A00, A10 등)")
    p.set_defaults(func=run_reverse)

    p = sub.add_parser("convert", help="좌표계 변환")
    add_common(p, "convert")
    p.add_argument("--from-coord", "--fromCoord", dest="fromCoord", required=True, help="원본 좌표계")
    p.add_argument("--to-coord", "--toCoord", dest="toCoord", required=True, help="대상 좌표계")
    p.add_argument("--lat", required=True)
    p.add_argument("--lon", required=True)
    p.set_defaults(func=run_convert)

    p = sub.add_parser("address", help="주소 변환 (지번↔도로명)")
    add_common(p, "address")
    p.add_argument(
        "--search-typ-cd",
        "--searchTypCd",
        dest="searchTypCd",
        default="NtoO",
        help="검색 유형 코드 (NtoO=도로명→지번, OtoN=지번→도로명). 기본 NtoO",
    )
    p.add_argument("--req-add", "--reqAdd", dest="reqAdd", required=True, help="요청 주소")
    p.add_argument("--req-multi", "--reqMulti", dest="reqMulti", help="다건 요청 플래그")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.set_defaults(func=run_address)

    p = sub.add_parser("near-road", help="좌표 → 가까운 도로 매칭")
    add_common(p, "near-road")
    p.add_argument("--lat", required=True)
    p.add_argument("--lon", required=True)
    p.set_defaults(func=run_near_road)

    p = sub.add_parser("postal", help="주소 → 우편번호")
    add_common(p, "postal")
    p.add_argument("--addr", required=True, help="주소 (예: 서울시 강남구 신사동)")
    p.add_argument("--address-flag", "--addressFlag", dest="addressFlag")
    p.add_argument("--page", type=int)
    p.add_argument("--count", type=int)
    p.set_defaults(func=run_postal)

    p = sub.add_parser("reverse-label", help="좌표 → 지역 레이블")
    add_common(p, "reverse-label")
    p.add_argument("--center-lat", "--centerLat", dest="centerLat", required=True)
    p.add_argument("--center-lon", "--centerLon", dest="centerLon", required=True)
    p.add_argument("--req-level", "--reqLevel", dest="reqLevel", default="15", help="요청 레벨 (15~19, 기본 15)")
    p.add_argument("--req-coord-type", "--reqCoordType", dest="reqCoordType", default="WGS84GEO")
    p.add_argument("--res-coord-type", "--resCoordType", dest="resCoordType", default="WGS84GEO")
    p.set_defaults(func=run_reverse_label)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        handle_error_and_exit(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
