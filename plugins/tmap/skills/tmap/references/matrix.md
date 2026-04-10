# 경로 매트릭스 (matrix.py)

**Product: `base`** (TMap API 기본 상품)
**Status: Verified 2026-04-11** — 실제 API 호출 성공

여러 출발지(origins) ↔ 여러 목적지(destinations) 간의 시간·거리를 한 번에 계산.

## 서브커맨드

| 서브커맨드 | 메서드 | 경로 |
|---|---|---|
| `od` | POST | `/tmap/matrix` |

## 필수 파라미터

`--origins-json '[...]'` / `--destinations-json '[...]'` (또는 파일 버전):

각 항목의 스키마 (공식):
```json
[
  {"lon": "127.027926", "lat": "37.497952", "poiId": "", "rpFlag": ""},
  {"lon": "126.977816", "lat": "37.566323"}
]
```

**중요**:
- `lon`/`lat` 값은 **문자열**이어야 합니다 (`"127.02"`, not `127.02`)
- `poiId`, `rpFlag`는 선택. POI 검색에서 얻은 값을 넘기면 정확도 향상
- `link` (`{"linkId":"...", "direction":"..."}`) 선택
- `name` 선택

## 선택 파라미터

- `--req-coord-type`, `--res-coord-type` — 좌표계 (기본 WGS84GEO)
- `--search-option` — 경로 옵션 (route.py와 동일)
- `--traffic-info Y` — 실시간 교통 반영

## 응답 구조

```json
{
  "meta": {
    "status": "Ok",
    "mapVersion": "20260407",
    "metric": "Recommendation",
    "transportMode": "Car",
    ...
  },
  "origins": [
    {"link": {"linkId": "0", "direction": "TwoWay"}, "poiId": "", "coordinate": {"latitude": 37.566323, "longitude": 126.977816}, ...}
  ],
  "destinations": [...],
  "matrixRoutes": [
    {
      "status": "Ok",
      "originIndex": 0,
      "destinationIndex": 0,
      "cost": 0,
      "duration": 1500,
      "distance": 14256.0,
      "toll": true
    }
  ]
}
```

주요 필드:
- `matrixRoutes[]`: O×D 조합 결과
- `originIndex`, `destinationIndex`: 원본 배열 인덱스 (0-base)
- `duration`: 초 단위
- `distance`: 미터 (float)
- `cost`: 통행료 (원)
- `toll`: 유료도로 사용 여부

## 요약

- `--summarize` 옵션으로 `matrixRoutes`를 표 형태로 압축 (originIndex/destinationIndex/duration/distance만)

## 용도

1. **가장 가까운 출발지 선택**: "집/회사/역 중에서 목적지까지 가장 빠른 곳"
   - origins: 3곳, destinations: 1곳 → 3개 결과 비교
2. **가장 가까운 목적지 선택**: "여러 매장 중 내 위치에서 가장 가까운 곳"
   - origins: 1곳, destinations: N곳
3. **운송·배송 라우팅**: 여러 배송지 간 모든 쌍의 거리·시간

## 예시

```bash
# 집/회사/역 → 코엑스
python3 matrix.py od \
  --origins-json '[
    {"lon":"126.977816","lat":"37.566323"},
    {"lon":"127.027926","lat":"37.497952"},
    {"lon":"126.924191","lat":"37.556853"}
  ]' \
  --destinations-json '[{"lon":"127.0595","lat":"37.5115"}]' \
  --traffic-info Y \
  --summarize standard --pretty
```

## 주의사항

- 조합 수(O×D)가 클수록 처리 시간 및 quota 비용 증가
- `lon`/`lat`는 **문자열**. 숫자로 넘기면 400 오류
- 응답의 `cost`는 통행료 (원). `toll`은 유료도로 통과 여부
- `meta.transportMode`는 `Car` 고정 (대중교통 매트릭스는 별도 엔드포인트)
