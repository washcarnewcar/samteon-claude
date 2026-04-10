#!/usr/bin/env python3
"""TMap 이동도로 매칭 (RoadAPI).

GPS 좌표 시퀀스를 실제 도로 위로 스냅.

서브커맨드:
  match       일반 매칭 (최대 100포인트)
              POST /tmap/road/matchToRoads?version=1
  match-500   500포인트
              POST /tmap/road/matchToRoads/500?version=1
  match-1000  1000포인트
              POST /tmap/road/matchToRoads/1000?version=1

공식 문서: https://skopenapi.readme.io/reference/roadapi-1
Content-Type: application/x-www-form-urlencoded (JSON이 아님)

필수 파라미터:
- responseType: 1=전체, 2=요청·매칭좌표 제외
- coords: "경도,위도|경도,위도|..." (pipe 구분 문자열)
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from tmap_client import (
    TmapClient,
    TmapAPIError,
    handle_error_and_exit,
    output_json,
    parse_json_body,
)

DEFAULT_PATHS = {
    "match": "/tmap/road/matchToRoads",
    "match-500": "/tmap/road/matchToRoads500",
    "match-1000": "/tmap/road/matchToRoads1000",
}


def run(args: argparse.Namespace) -> None:
    coords_str = args.coords
    if coords_str is None and args.coords_file:
        coords_str = Path(args.coords_file).read_text(encoding="utf-8").strip()
    if not coords_str:
        print("coords가 비어있습니다 ('경도,위도|경도,위도|...' 형식).", file=sys.stderr)
        sys.exit(2)

    form_data = {
        "responseType": args.responseType,
        "coords": coords_str,
    }
    override = parse_json_body(args.raw_json)
    if override:
        form_data.update(override)

    # form-urlencoded body
    body_bytes = urllib.parse.urlencode(form_data).encode("utf-8")

    client = TmapClient()
    url = client._url(args.path, query={"version": args.version})
    req = urllib.request.Request(
        url,
        data=body_bytes,
        method="POST",
        headers={
            "appKey": client.app_key,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=client.timeout) as resp:
            content = resp.read()
            resp_json = json.loads(content.decode("utf-8")) if content else None
    except urllib.error.HTTPError as e:
        try:
            body_text = json.loads(e.read().decode("utf-8"))
        except Exception:
            body_text = ""
        raise TmapAPIError(e.code, body_text, url) from e

    if args.output_full:
        Path(args.output_full).write_text(json.dumps(resp_json, ensure_ascii=False, indent=2), encoding="utf-8")
    output_json(resp_json, pretty=args.pretty)


def main() -> int:
    parser = argparse.ArgumentParser(prog="mapmatch.py", description="TMap 이동도로 매칭 얇은 래퍼")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for cmd, default_path in DEFAULT_PATHS.items():
        p = sub.add_parser(cmd, help=f"POST {default_path}")
        p.add_argument("--json", dest="raw_json")
        p.add_argument("--path", default=default_path)
        p.add_argument("--version", default="1")
        p.add_argument("--output-full", metavar="PATH")
        p.add_argument("--pretty", action="store_true")
        p.add_argument(
            "--response-type",
            "--responseType",
            dest="responseType",
            default="1",
            choices=["1", "2"],
            help="1=전체, 2=요청/매칭 좌표 제외",
        )
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--coords", help="pipe 구분 좌표 문자열 '경도,위도|경도,위도|...'")
        group.add_argument("--coords-file", help="위 형식의 문자열이 담긴 파일")
        p.set_defaults(func=run)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        handle_error_and_exit(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
