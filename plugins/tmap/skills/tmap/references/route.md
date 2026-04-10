# 경로안내 (route.py)

**Product: `base`** (TMap API 기본 상품)
**Status: Verified 2026-04-11** — car, pedestrian, distance, 타임머신(arrival) 실제 API 호출 성공

티맵 자동차/보행자/직선거리 경로 API. 공식 문서: https://skopenapi.readme.io/reference (TMAP 섹션의 경로안내).

## 서브커맨드와 엔드포인트

| 서브커맨드 | 메서드 | 경로 |
|---|---|---|
| `car` | POST | `/tmap/routes?version=1` |
| `pedestrian` | POST | `/tmap/routes/pedestrian?version=1` |
| `distance` | GET | `/tmap/routes/distance?version=1` |

## 자동차 경로 (`car`) 주요 파라미터

필수:
- `--start-x` / `--startX` — 출발 경도 (WGS84GEO 기준)
- `--start-y` / `--startY` — 출발 위도
- `--end-x` / `--endX` — 도착 경도
- `--end-y` / `--endY` — 도착 위도

선택 (자주 쓰는 것):
- `--start-name` / `--end-name` — 출발/도착지 이름 (URL 인코딩 자동)
- `--search-option` / `--searchOption` — 경로 탐색 옵션:
  - `0` 교통최적+추천 (기본)
  - `1` 무료우선
  - `2` 최단
  - `3` 고속도로 우선
  - `4` 통행료 무료
  - `10` 최적+추천
  - `12` 최단+실시간
  - `19` 추천+실시간
  - (기타 세부 옵션은 공식 문서 참조)
- `--traffic-info Y` / `--trafficInfo` — 실시간 교통정보 반영
- `--car-type` / `--carType` — 차종 1(승용)~6(대형)
- `--pass-list "127.0,37.5_127.1,37.6"` — 경유지 (2~3개 간단한 경유지일 때)
- `--angle` — 출발 각도 0~360 (이전 진행 방향 정보)

타임머신 예측 (출발/도착시간 기반):
- `--prediction-type departure` — 해당 시각 출발
- `--prediction-type arrival` — 해당 시각 도착 (역산)
- `--prediction-time "202604100900"` — YYYYMMDDHHmm (KST 가정). 또는 ISO8601

좌표계:
- `--req-coord-type` / `--res-coord-type` — 기본 `WGS84GEO`. 다른 값: `KATEC`, `EPSG3857`, `WGS84GEORAD` 등

## 보행자 경로 (`pedestrian`) 주의사항

- `startName` 과 `endName` 이 **필수**입니다 (자동차와 다름)
- `searchOption` 값이 자동차와 다름:
  - `0` 추천
  - `4` 대로우선
  - `10` 최단
  - `30` 계단 제외
- `passList` 는 간단한 경유지만 (자세한 건 waypoints.py 사용)

## 직선거리 (`distance`)

두 좌표 사이의 직선 거리만 미터 단위로 반환. GET 방식이라 쿼리 파라미터:
- `--start-x`, `--start-y`, `--end-x`, `--end-y`
- `--req-coord-type`, `--res-coord-type`

실제 경로 거리가 아니라 평면 직선 거리임에 주의.

## 응답 구조 (car/pedestrian)

GeoJSON FeatureCollection 형식:
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [127.02, 37.49]},
      "properties": {
        "totalDistance": 12345,
        "totalTime": 1800,
        "totalFare": 0,
        "taxiFare": 15000,
        "pointIndex": "0",
        "description": "출발지"
      }
    },
    {
      "type": "Feature",
      "geometry": {"type": "LineString", "coordinates": [[...], [...]]},
      "properties": {...}
    },
    // ... 많은 Point (턴바이턴) + LineString (구간)
  ]
}
```

- `totalDistance` — 미터
- `totalTime` — 초
- `totalFare` — 통행료 원
- `taxiFare` — 예상 택시 요금 원 (자동차만)
- Point feature의 `description` — 턴바이턴 안내 문구

응답이 수백 KB ~ MB 단위로 클 수 있습니다. 사용자 응답용이면 반드시 `--summarize` 사용.

## 요약 레벨

- `--summarize minimal` — totalDistance, totalTime, totalFare, taxiFare만
- `--summarize standard` — + 시작/끝 좌표 + 턴바이턴 10개 (기본)
- `--summarize full` — + 전체 턴바이턴
- `--turns N` — 턴바이턴 개수 수동 지정

## 예시

```bash
# 기본 자동차 경로 (요약 포함)
python3 route.py car \
  --start-x 127.0276 --start-y 37.4979 \
  --end-x 126.9236 --end-y 37.5663 \
  --summarize standard

# 실시간 교통 반영
python3 route.py car \
  --start-x 127.0276 --start-y 37.4979 \
  --end-x 126.9236 --end-y 37.5663 \
  --search-option 10 --traffic-info Y \
  --summarize standard

# 타임머신: 내일 오전 9시 도착 기준 역산
python3 route.py car \
  --start-x 127.1 --start-y 37.4 \
  --end-x 126.97 --end-y 37.57 \
  --prediction-type arrival \
  --prediction-time "202604110900" \
  --summarize standard

# 보행자
python3 route.py pedestrian \
  --start-name "서울시청" --end-name "덕수궁" \
  --start-x 126.9779 --start-y 37.5666 \
  --end-x 126.9751 --end-y 37.5659 \
  --search-option 0 \
  --summarize standard

# 파라미터가 부족하거나 새 파라미터가 필요하면 --json 사용
python3 route.py car \
  --start-x 127.0 --start-y 37.5 --end-x 127.1 --end-y 37.6 \
  --json '{"carType":"3","tollgateCarType":"1","reservedField":"custom"}' \
  --summarize standard
```

## 주의사항

- 좌표 순서는 **경도(X) 먼저, 위도(Y) 나중**. 일반적인 "위도, 경도" 순서와 반대
- 한국 내 좌표만 지원
- appKey 할당량 초과 시 `TmapAPIError 429` 발생
- 출발지와 도착지가 같거나 너무 가까우면 오류
