# 유가정보 (fuel.py)

**Product: `base`** (TMap API 기본 상품)
**Status: Verified 2026-04-11** — 실제 API 호출 성공, SK 서광셀프 주유소 경유 1,960원 등 가격 확인

주유소와 전기차 충전소 검색 및 가격 조회. 별도 엔드포인트가 아니라 **POI 주변 카테고리 검색 API의 특수 케이스**입니다.

## 서브커맨드

| 서브커맨드 | 메서드 | 경로 |
|---|---|---|
| `nearby` | GET | `/tmap/pois/search/around` (POI API 재사용) |
| `detail` | GET | `/tmap/pois/{poiId}` (POI detail 재사용) |

**주의**: 원래 `/tmap/puzzle/pois` 경로를 추측으로 썼으나 **존재하지 않습니다**. 실제로는 POI API와 동일한 엔드포인트를 재사용합니다.

## nearby: 주변 주유소/충전소

**필수**:
- `--center-lat` / `--centerLat`
- `--center-lon` / `--centerLon`
- `--radius` — km (1~33)

**선택**:
- `--categories` 기본 `"주유소"` (한글 텍스트). 전기차는 `"전기차충전소"`
- `--data-kind` / `--dataKind` — 데이터 종류 필터:
  - `3` = 주유소
  - `6` = 전기차 충전소
- `--brand-name` — 브랜드 필터 (예: `"SK"`, `"GS"`, `"S-OIL"`)
- `--count`, `--page` — 페이징
- `--sort` — `price` (가격순), `distance` (거리순)
- `--req-coord-type`, `--res-coord-type`

### 예시

```bash
# 강남역 근처 주유소 상위 5개 (가격 포함)
python3 fuel.py nearby \
  --center-lat 37.497952 --center-lon 127.027926 \
  --radius 3 --count 5 --pretty

# 가격순 정렬
python3 fuel.py nearby \
  --center-lat 37.5547 --center-lon 126.9707 \
  --radius 2 --categories "주유소" \
  --sort price --count 10 --pretty

# 특정 브랜드만
python3 fuel.py nearby \
  --center-lat 37.5 --center-lon 127.0 \
  --radius 5 --brand-name "SK" --sort distance

# 전기차 충전소
python3 fuel.py nearby \
  --center-lat 37.5 --center-lon 127.0 \
  --radius 3 --categories "전기차충전소"
```

## detail: POI 상세 (주유소 정보)

```bash
python3 fuel.py detail --poi-id 466860 --pretty
```

POI detail API (`/tmap/pois/{poiId}`)를 재사용합니다. `--poi-id`는 `nearby` 응답의 POI ID.

## 응답 구조

`nearby` 응답은 표준 POI 검색 응답 + 가격 필드:
```json
{
  "searchPoiInfo": {
    "totalCount": 34,
    "count": 5,
    "pois": {
      "poi": [
        {
          "id": "466860",
          "name": "SK 서광셀프주유소",
          "telNo": "025624855",
          "frontLat": "37.49449135",
          "frontLon": "127.03493459",
          "upperAddrName": "서울",
          "middleAddrName": "강남구",
          "lowerAddrName": "역삼동",
          "roadName": "역삼로",
          "buildingNo1": "142",
          "radius": "0.751",
          "dataKind": "3",
          "stId": "SK",
          "hhPrice": "1990",
          "ggPrice": "1960",
          "llPrice": "0",
          "highHhPrice": "2480",
          "highGgPrice": "0",
          "oilBaseSdt": "20260410"
        }
      ]
    }
  }
}
```

가격 필드:
- `hhPrice`: 휘발유 가격 (원)
- `ggPrice`: 경유 가격 (원)
- `llPrice`: LPG 가격 (원, 0이면 미취급)
- `highHhPrice`: 고급 휘발유
- `highGgPrice`: 고급 경유
- `oilBaseSdt`: 가격 기준일 (YYYYMMDD)

기타 필드:
- `stId`: 브랜드 ID (SK, GS, HD, SO 등)
- `dataKind`: `3`=주유소, `6`=전기차충전소
- `radius`: 중심으로부터 거리(km)

## 주의사항

- 가격은 Opinet 데이터 기반 — 실시간성 몇 시간 지연 가능
- `llPrice=0`은 LPG 취급 안 함을 의미
- 가격 정렬은 보통 휘발유 기준
- 전기차 충전소는 가격 대신 충전 요금 필드가 다를 수 있음 (응답 구조 확인)
- 브랜드명은 한글 (`SK`, `GS`, `S-OIL`, `현대오일뱅크`) 또는 stId (`SK`, `GS`, `SO`, `HD`)
