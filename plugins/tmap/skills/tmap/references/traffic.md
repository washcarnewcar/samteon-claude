# 실시간 교통정보 (traffic.py)

**Product: `base`** (TMap API 기본 상품에 포함됨 — **별도 상품 아님**)
**Status: Verified 2026-04-11** — 호출 성공(200 OK). 빈 features가 반환될 수 있음(시간/지역 따라 데이터 편차)

현재 도로의 교통 상황 (정체/서행/원활) 및 사고 정보.

## 서브커맨드

| 서브커맨드 | 메서드 | 경로 |
|---|---|---|
| `live` | GET | `/tmap/traffic` |

## 파라미터

모두 선택이지만 의미 있는 응답을 받으려면 `trafficType` + 좌표 정보는 필수:

**중심 반경 방식** (`trafficType=AROUND`):
- `--center-lat` / `--centerLat`
- `--center-lon` / `--centerLon`
- `--radius` — **1~9** (300m~2700m 단위. km 아님!)

**bbox 방식** (`trafficType=AUTO`):
- `--min-lat`, `--min-lon`, `--max-lat`, `--max-lon`

공통:
- `--traffic-type` — `AUTO` / `AROUND` / `POINT` / `ACC` (enum). 미지정 가능하지만 명시 권장
- `--zoom-level` — 1~19 (기본 7)
- `--req-coord-type`, `--res-coord-type` — 기본 `WGS84GEO`
- `--sort` — 기본 `index`
- `--callback` — JSONP 콜백

**중요**:
- 이전 버전에서 쓰던 `minX/maxX`는 **틀린 이름**입니다. 반드시 `minLat/minLon/maxLat/maxLon` 사용
- `trafficType`은 숫자가 아닌 **enum 문자열**
- `radius`는 km 단위가 아닌 **1~9 번호** (1=300m, 2=600m, ..., 9=2700m)

## 예시

```bash
# 중심 반경 방식 (AROUND)
python3 traffic.py live \
  --center-lat 37.5665 --center-lon 126.978 \
  --radius 3 --traffic-type AROUND --zoom-level 15 \
  --req-coord-type WGS84GEO --res-coord-type WGS84GEO

# bbox 방식 (AUTO)
python3 traffic.py live \
  --min-lat 37.55 --min-lon 126.97 \
  --max-lat 37.58 --max-lon 127.00 \
  --traffic-type AUTO --zoom-level 15
```

## 응답 구조

GeoJSON FeatureCollection:
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "LineString", "coordinates": [[...]]},
      "properties": {
        "congestion": 2,
        "description": "서행",
        "roadName": "강남대로",
        "linkId": "...",
        "speed": 15
      }
    }
  ]
}
```

`congestion` 값 (일반적):
- `1` 원활 (녹색)
- `2` 서행 (노란색)
- `3` 지체 (주황색)
- `4` 정체 (빨간색)

## 주의사항

- 새벽/심야 시간대에는 데이터가 없어 `features` 배열이 비어 있을 수 있음. 이것이 오류는 아님 (200 OK 반환)
- `features`가 비어있어도 호출 자체는 성공
- 줌 레벨이 너무 낮거나 반경이 너무 크면 데이터가 없을 수 있음 → 줌을 높이고 반경을 줄여볼 것
- 사용자에게 제시할 때는 정체 구간(congestion >= 3)만 필터링해서 요약하면 깔끔
