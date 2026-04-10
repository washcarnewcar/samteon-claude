#!/usr/bin/env python3
"""TMap 경로안내 (자동차/보행자/직선거리).

티맵 API의 얇은 래퍼. 서브커맨드 = 티맵 엔드포인트 1:1.

서브커맨드:
  car         자동차 경로   POST /tmap/routes?version=1
  pedestrian  보행자 경로   POST /tmap/routes/pedestrian?version=1
  distance    직선거리      GET  /tmap/routes/distance?version=1

모든 서브커맨드는 --json, --summarize, --output-full, --pretty 공통 지원.
타임머신 예측은 car 서브커맨드에서 --prediction-type / --prediction-time 옵션으로 활성화.
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


def add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", dest="raw_json", help="raw JSON 요청 바디를 직접 전달 (다른 플래그와 병합, raw가 우선)")
    p.add_argument(
        "--summarize",
        nargs="?",
        const="standard",
        choices=["minimal", "standard", "full"],
        help="응답을 요약하여 출력. 값 없이 쓰면 standard.",
    )
    p.add_argument("--turns", type=int, default=None, help="요약 시 턴바이턴 최대 개수 (기본 standard=10, full=무제한)")
    p.add_argument("--output-full", metavar="PATH", help="전체 원본 응답을 파일에 저장. stdout에는 요약 또는 원본 출력.")
    p.add_argument("--pretty", action="store_true", help="stdout JSON을 들여쓰기해서 출력")
    p.add_argument("--version", default="1", help="API version 쿼리 파라미터 (기본 1)")


def add_route_params(p: argparse.ArgumentParser, *, mode: str) -> None:
    # 출발/도착 좌표 (모든 경로 서브커맨드 공통)
    p.add_argument("--start-x", "--startX", dest="startX", help="출발 경도 (startX)")
    p.add_argument("--start-y", "--startY", dest="startY", help="출발 위도 (startY)")
    p.add_argument("--end-x", "--endX", dest="endX", help="도착 경도 (endX)")
    p.add_argument("--end-y", "--endY", dest="endY", help="도착 위도 (endY)")
    p.add_argument("--start-name", "--startName", dest="startName", help="출발지 이름 (보행자 경로는 필수)")
    p.add_argument("--end-name", "--endName", dest="endName", help="도착지 이름 (보행자 경로는 필수)")
    p.add_argument(
        "--req-coord-type",
        "--reqCoordType",
        dest="reqCoordType",
        default="WGS84GEO",
        help="요청 좌표계 (기본 WGS84GEO)",
    )
    p.add_argument(
        "--res-coord-type",
        "--resCoordType",
        dest="resCoordType",
        default="WGS84GEO",
        help="응답 좌표계 (기본 WGS84GEO)",
    )
    p.add_argument("--angle", type=int, help="출발 각도 (0~360)")
    p.add_argument(
        "--search-option",
        "--searchOption",
        dest="searchOption",
        help="경로탐색 옵션 (자동차: 0 추천, 1 무료우선, 2 최단, 3 고속도로우선, 4 통행료무료, 10 최적, 12 최단+실시간, 19 추천+실시간 등 / 보행자: 0 추천, 4 대로우선, 10 최단, 30 계단제외)",
    )
    if mode == "car":
        p.add_argument("--traffic-info", "--trafficInfo", dest="trafficInfo", choices=["Y", "N"], help="실시간 교통정보 반영")
        p.add_argument("--car-type", "--carType", dest="carType", help="차종 (1~6)")
        p.add_argument("--tollgate-car-type", "--tollgateCarType", dest="tollgateCarType", help="통행료 차종")
        p.add_argument("--total-value", "--totalValue", dest="totalValue", help="전기/수소차 관련 값")
        p.add_argument("--pass-list", "--passList", dest="passList", help="경유지 리스트 'X1,Y1_X2,Y2' 형식")
        p.add_argument("--pass-search-flag", "--passSearchFlag", dest="passSearchFlag", help="경유지 검색 플래그")
        p.add_argument("--direction-option", "--directionOption", dest="directionOption", help="경로 방향 옵션")
        p.add_argument("--route-type", "--routeType", dest="routeType", help="경로 유형")
        p.add_argument("--sort", help="경로 정렬 기준")
        p.add_argument("--detail-pos-flag", "--detailPosFlag", dest="detailPosFlag", help="상세 좌표 플래그")
        # 타임머신
        p.add_argument(
            "--prediction-type",
            "--predictionType",
            dest="predictionType",
            choices=["departure", "arrival"],
            help="타임머신 예측 유형 (departure=출발시간 기준, arrival=도착시간 기준)",
        )
        p.add_argument(
            "--prediction-time",
            "--predictionTime",
            dest="predictionTime",
            help="타임머신 예측 시각 (ISO8601 형식, 예: 2026-04-10T09:00:00+0900)",
        )
    if mode == "pedestrian":
        p.add_argument("--pass-list", "--passList", dest="passList", help="경유지 리스트 'X1,Y1_X2,Y2' 형식")
        p.add_argument("--sort", help="경로 정렬 기준")


def build_body(args: argparse.Namespace, *, mode: str) -> dict:
    """CLI args를 티맵 API 요청 바디로 변환."""
    body: dict = {}
    field_names = [
        "startX",
        "startY",
        "endX",
        "endY",
        "startName",
        "endName",
        "reqCoordType",
        "resCoordType",
        "angle",
        "searchOption",
        "trafficInfo",
        "carType",
        "tollgateCarType",
        "totalValue",
        "passList",
        "passSearchFlag",
        "directionOption",
        "routeType",
        "sort",
        "detailPosFlag",
        "predictionType",
        "predictionTime",
    ]
    for name in field_names:
        val = getattr(args, name, None)
        if val is not None:
            body[name] = val
    # 출발/도착지 이름 URL 인코딩 (티맵 API가 요구)
    for k in ("startName", "endName"):
        if k in body and isinstance(body[k], str):
            from urllib.parse import quote
            if all(ord(c) < 128 for c in body[k]):
                pass  # 이미 ASCII면 그대로
            else:
                body[k] = quote(body[k], safe="")
    return body


def run_car(args: argparse.Namespace) -> None:
    client = TmapClient()
    body = build_body(args, mode="car")
    override = parse_json_body(args.raw_json)
    body = merge_body(body, override)
    resp = client.post("/tmap/routes", body=body, query={"version": args.version})
    handle_output(resp, args, kind="route")


def run_pedestrian(args: argparse.Namespace) -> None:
    client = TmapClient()
    body = build_body(args, mode="pedestrian")
    override = parse_json_body(args.raw_json)
    body = merge_body(body, override)
    resp = client.post("/tmap/routes/pedestrian", body=body, query={"version": args.version})
    handle_output(resp, args, kind="route")


def run_distance(args: argparse.Namespace) -> None:
    client = TmapClient()
    query = {
        "version": args.version,
        "startX": args.startX,
        "startY": args.startY,
        "endX": args.endX,
        "endY": args.endY,
        "reqCoordType": args.reqCoordType,
        "resCoordType": args.resCoordType,
    }
    override = parse_json_body(args.raw_json)
    if override:
        query.update(override)
    resp = client.get("/tmap/routes/distance", query=query)
    handle_output(resp, args, kind=None)


def handle_output(resp, args: argparse.Namespace, *, kind: str | None) -> None:
    if args.output_full:
        Path(args.output_full).write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    data = resp
    if args.summarize and kind:
        data = apply_summarize(resp, kind=kind, level=args.summarize, extra={"turns": args.turns})
    output_json(data, pretty=args.pretty)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="route.py",
        description="TMap 경로안내 얇은 래퍼 (자동차/보행자/직선거리)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    car = sub.add_parser("car", help="자동차 경로 (POST /tmap/routes)")
    add_common_args(car)
    add_route_params(car, mode="car")
    car.set_defaults(func=run_car)

    ped = sub.add_parser("pedestrian", help="보행자 경로 (POST /tmap/routes/pedestrian)")
    add_common_args(ped)
    add_route_params(ped, mode="pedestrian")
    ped.set_defaults(func=run_pedestrian)

    dist = sub.add_parser("distance", help="직선거리 (GET /tmap/routes/distance)")
    add_common_args(dist)
    add_route_params(dist, mode="distance")
    dist.set_defaults(func=run_distance)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        handle_error_and_exit(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
