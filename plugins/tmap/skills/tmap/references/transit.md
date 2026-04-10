# 대중교통 (transit.py)

**Product: `transit`** (TMap 대중교통, 별도 상품 신청 필요)
**Status: Verified 2026-04-11** — route, summary 두 서브커맨드 실제 API 호출 성공 (상품 신청 후)

버스, 지하철, 기차, 항공, 해운을 통합한 대중교통 경로 안내. 자동차/보행자 경로와 엔드포인트 및 응답 구조가 완전히 다릅니다.

## ⚠️ 별도 상품 신청 필수

**TMap 대중교통 API**는 SK Open API에서 **TMap API와 다른 상품**입니다. 같은 AppKey를 공유하지만, 대중교통 상품을 **별도로 신청**해야 사용할 수 있습니다.

신청 방법: https://openapi.sk.com/ → 앱 관리 → 상품 추가 → "TMap 대중교통" 선택.

신청하지 않은 경우 다음 오류가 발생합니다:
```
TMap API 오류 403 (https://apis.openapi.sk.com/transit/routes?version=1)
{"error":{"id":"403","category":"gw","code":"INVALID_API_KEY","message":"Forbidden"}}
```

이 오류가 나면 권한 문제이지 스크립트 버그가 아닙니다. 사용자에게 상품 추가 신청을 안내하세요.

## 서브커맨드

| 서브커맨드 | 목적 | 메서드 | 경로 |
|---|---|---|---|
| `route` | 대중교통 경로 (상세) | POST | `/transit/routes` |
| `summary` | 대중교통 경로 요약 | POST | `/transit/routes/sub` |

## 필수 파라미터

- `--start-x` / `--startX` — 출발 경도
- `--start-y` / `--startY` — 출발 위도
- `--end-x` / `--endX` — 도착 경도
- `--end-y` / `--endY` — 도착 위도

## 선택 파라미터

- `--lang 0` — 한국어 (기본), `1` 영어
- `--count N` — 반환할 경로 옵션 개수 (기본 3~5)
- `--format json`
- `--search-dttm "YYYYMMDDHHmm"` — 검색 일시 (미래 시간도 가능)

## 응답 구조

```json
{
  "metaData": {
    "requestParameters": {...},
    "plan": {
      "itineraries": [
        {
          "totalTime": 3600,
          "totalDistance": 20000,
          "totalWalkTime": 300,
          "transferCount": 1,
          "fare": {
            "regular": {"totalFare": 2800, "currency": {"symbol": "원"}}
          },
          "legs": [
            {
              "mode": "WALK",
              "sectionTime": 300,
              "distance": 500,
              "start": {"name": "출발지", "lat": 37.5, "lon": 127.0},
              "end": {"name": "강남역", "lat": 37.49, "lon": 127.03},
              "steps": [...]
            },
            {
              "mode": "SUBWAY",
              "sectionTime": 1800,
              "route": "수도권2호선",
              "routeColor": "009D3E",
              "start": {"name": "강남역"},
              "end": {"name": "시청"},
              "passStopList": {...}
            },
            // ... more legs
          ]
        }
      ]
    }
  }
}
```

주요 필드:
- `itineraries` — 경로 옵션 배열
- `totalTime` — 총 소요시간(초)
- `totalWalkTime` — 도보 시간
- `transferCount` — 환승 횟수
- `fare.regular.totalFare` — 일반 요금(원)
- `legs` — 구간 리스트
- 구간의 `mode`: `WALK`, `BUS`, `SUBWAY`, `EXPRESSBUS`, `TRAIN`, `AIRPLANE`, `FERRY`

## 요약

- `--summarize minimal` — 경로 옵션별 totalTime만
- `--summarize standard` — + 환승 수 + 구간별 요약
- `--summarize full` — + 모든 구간 상세
- `--options N` — 요약에 포함할 경로 옵션 개수 (기본 무제한)

## 예시

```bash
# 강남역 → 인천공항 (기본)
python3 transit.py route \
  --start-x 127.0276 --start-y 37.4979 \
  --end-x 126.4407 --end-y 37.4601 \
  --summarize standard --options 3

# 영어 응답
python3 transit.py route \
  --start-x 127.0 --start-y 37.5 --end-x 127.1 --end-y 37.6 \
  --lang 1 --count 5

# 요약 엔드포인트 (경로 후보만 간단히)
python3 transit.py summary \
  --start-x 127.0 --start-y 37.5 --end-x 127.1 --end-y 37.6 \
  --summarize standard
```

## 주의사항

- 응답이 매우 큼 (수백 KB). 반드시 `--summarize` 권장
- 대중교통이 없거나 너무 가까운 거리는 빈 결과 반환
- `count`를 높이면 응답 크기 비례 증가
- 미래 시각 검색(`searchDttm`)은 시간표 기반 예측 — 정확하지 않을 수 있음
- 버스 노선 색상(`routeColor`)은 HEX 형식 (예: `009D3E`)
