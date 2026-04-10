#!/usr/bin/env python3
"""TMap 온보딩: 사용자의 AppKey에 어떤 상품이 활성화되어 있는지 감지.

서브커맨드:
  status   저장된 상태를 JSON으로 출력 (API 호출 없음)
  check    각 상품에 최소 비용 호출로 실제 활성화 확인, state 저장, JSON 출력
  refresh  check의 별칭. 사용자가 "신청했어" 언급 시 자동 호출

추적 상품 (2개, 서로 독립):
  base     TMap API (경로/POI/지오코딩/경유지/유가/매트릭스/도로매칭/정적지도/지오펜싱/교통정보)
  transit  TMap 대중교통 (버스/지하철/기차 경로)

상태 값: enabled | disabled | unknown

사용 예:
  python3 onboarding.py status
  python3 onboarding.py check
  python3 onboarding.py refresh
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys

from tmap_client import (
    MissingKeyError,
    PRODUCT_KEYS,
    TmapAPIError,
    TmapClient,
    handle_error_and_exit,
    load_product_status,
    save_product_status,
)


def cmd_status() -> int:
    """저장된 상태만 출력 (API 호출 없음)."""
    status = load_product_status()
    # API 키 존재 여부도 함께 표시 (없으면 client 생성 시 에러)
    try:
        TmapClient()  # 키만 로드, 호출 X
        status["app_key"] = "present"
    except MissingKeyError:
        status["app_key"] = "missing"
    print(json.dumps(status, ensure_ascii=False))
    return 0


def check_base(client: TmapClient) -> str:
    """TMap API 기본 상품 활성화 확인. 간단한 지오코딩 호출."""
    try:
        client.get(
            "/tmap/geo/fullAddrGeo",
            query={
                "version": "1",
                "format": "json",
                "coordType": "WGS84GEO",
                "fullAddr": "서울시청",
            },
        )
        return "enabled"
    except TmapAPIError as e:
        return _interpret_error(e)
    except Exception:
        return "unknown"


def check_transit(client: TmapClient) -> str:
    """TMap 대중교통 상품 활성화 확인. 최소 valid body로 호출."""
    try:
        client.post(
            "/transit/routes",
            body={
                "startX": "127.027926",
                "startY": "37.497952",
                "endX": "126.977816",
                "endY": "37.566323",
                "count": 1,
                "lang": 0,
                "format": "json",
            },
            query={"version": "1"},
        )
        return "enabled"
    except TmapAPIError as e:
        return _interpret_error(e)
    except Exception:
        return "unknown"


def _interpret_error(e: TmapAPIError) -> str:
    """TmapAPIError를 상태 값으로 해석.

    - 401/403 권한 오류 → disabled (상품 미등록)
    - 429 QUOTA_EXCEEDED → enabled (권한 있음, 일시 할당량 초과)
    - 400 파라미터 오류 → enabled (스크립트 자체 문제일 수 있음, 일단 권한은 있음)
    - 기타 → unknown
    """
    status = e.status
    body = e.body if isinstance(e.body, dict) else {}
    error = body.get("error") or {}
    code = (error.get("code") or "").upper()

    if status in (401, 403):
        if "INVALID_API_KEY" in code or "MISSING_AUTHENTICATION" in code or "FORBIDDEN" in code:
            return "disabled"
        return "disabled"  # 401/403은 권한 문제로 간주

    if status == 429 and "QUOTA" in code:
        return "enabled"  # quota 초과지만 권한은 있음

    if status == 400:
        return "enabled"  # 파라미터 문제이지 권한 문제는 아님

    return "unknown"


def cmd_check() -> int:
    """실제 API 호출로 각 상품 활성화 여부 판정 후 저장."""
    try:
        client = TmapClient()
    except MissingKeyError as e:
        print(str(e), file=sys.stderr)
        return 3

    results: dict[str, str] = {}
    for product in PRODUCT_KEYS:
        if product == "base":
            results[product] = check_base(client)
        elif product == "transit":
            results[product] = check_transit(client)

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results["last_checked"] = now

    save_product_status(results)

    output = dict(results)
    output["app_key"] = "present"
    print(json.dumps(output, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="onboarding.py",
        description="TMap 상품 활성화 상태 감지 및 캐싱",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="저장된 상태를 JSON으로 출력 (API 호출 없음)")
    sub.add_parser("check", help="실제 API 호출로 활성화 여부 확인 후 저장")
    sub.add_parser("refresh", help="check의 별칭 (사용자 '신청했어' 시)")

    args = parser.parse_args()
    try:
        if args.cmd == "status":
            return cmd_status()
        if args.cmd in ("check", "refresh"):
            return cmd_check()
    except Exception as e:
        handle_error_and_exit(e)
    return 1


if __name__ == "__main__":
    sys.exit(main())
