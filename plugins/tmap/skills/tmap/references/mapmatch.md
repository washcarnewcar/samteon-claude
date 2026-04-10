# 이동도로 매칭 (mapmatch.py)

**Product: `base`** (TMap API 기본 상품)
**Status: Verified 2026-04-11** — 3개 variant 모두 실제 API 호출 성공

GPS 좌표 시퀀스를 실제 도로 위로 스냅(매칭)합니다.

## 서브커맨드

| 서브커맨드 | 경로 | 용량 |
|---|---|---|
| `match` | `POST /tmap/road/matchToRoads` | 최대 100 포인트 |
| `match-500` | `POST /tmap/road/matchToRoads500` | 최대 500 포인트 |
| `match-1000` | `POST /tmap/road/matchToRoads1000` | 최대 1000 포인트 |

**주의**: 500/1000 버전은 `/matchToRoads/500`이 아니라 **`/matchToRoads500`** (슬래시 없음)

## 필수 파라미터

- `--coords` 또는 `--coords-file`: 좌표 문자열

**좌표 형식**:
```
"경도,위도|경도,위도|경도,위도..."
```

예: `"127.02789,37.49796|127.02850,37.49850|127.02900,37.49900"`

- **pipe (`|`) 구분**. JSON 배열이 아닙니다
- 경도(longitude)가 먼저, 위도(latitude)가 나중

- `--response-type` 기본 `1`:
  - `1` = 전체 응답
  - `2` = 요청·매칭 좌표 제외 (경량화)

## HTTP 특수성

- `Content-Type: application/x-www-form-urlencoded` (JSON 아님)
- 바디는 `coords=...&responseType=1`

스크립트가 자동으로 form 인코딩 처리함.

## 예시

```bash
# 기본 매칭
python3 mapmatch.py match \
  --coords "127.02789,37.49796|127.02850,37.49850|127.02900,37.49900"

# 500 포인트 (많은 GPS 좌표)
python3 mapmatch.py match-500 \
  --coords-file /tmp/gps_trace.txt \
  --response-type 2

# 1000 포인트
python3 mapmatch.py match-1000 \
  --coords-file /tmp/long_trace.txt \
  --output-full /tmp/matched.json
```

## 응답 구조

```json
{
  "resultData": {
    "header": {
      "totalDistance": 123,
      "totalPointCount": 8,
      "matchedLinkCount": 4
    },
    "matchedPoints": [
      {
        "linkId": "9258",
        "matchedLocation": {"latitude": 37.4979, "longitude": 127.0278},
        "tLinkId": "1028232",
        "idxName": "57160000",
        "sourceLocation": {"latitude": 37.49796, "longitude": 127.02789},
        "sourceIndex": 0,
        "speed": 50,
        "roadCategory": 5
      }
    ]
  }
}
```

- `matchedPoints[]`: 원본 좌표가 도로 위 좌표로 스냅된 결과
- `sourceIndex`: 원본 coords 배열의 인덱스
- `linkId`, `tLinkId`: 도로 링크 ID
- `speed`: 해당 링크의 제한속도
- `roadCategory`: 도로 분류

## 용도

- GPS 궤적 정제 (노이즈가 있는 좌표를 도로 위로 스냅)
- 드라이빙 분석 (실제 주행 경로 재구성)
- 운송 서비스 정산 (실제 도로 기반 거리)

## 주의사항

- 좌표가 너무 듬성듬성하면 정확도가 떨어짐
- `match-500`/`match-1000`은 대량 데이터 전용. 100개 이하는 `match` 사용
- 응답이 클 수 있으므로 `--output-full`로 파일 저장 후 필요한 부분만 조회 권장
- **좌표 순서**: `경도,위도` (longitude first). 일반 "위도,경도" 표기와 반대
