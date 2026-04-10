# 지오펜싱 (geofence.py)

**Product: `base`** (TMap API 기본 상품)
**Status: Verified 2026-04-11** — 2개 서브커맨드 실제 API 호출 성공

영역(행정구역) 기반 공간 검색 및 경계 조회.

## 서브커맨드

| 서브커맨드 | 메서드 | 경로 |
|---|---|---|
| `spatial-search` | GET | `/tmap/geofencing/regions` |
| `area` | GET | `/tmap/geofencing/regions/{regionId}` |

## spatial-search: 공간 검색

행정구역을 키워드 또는 좌표로 검색합니다.

**필수 파라미터**:
- `--categories`: `city_do` | `gu_gun` | `legalDong` | `adminDong`
- `--search-type`: `KEYWORD` | `COORDINATES`
- `--count` 기본 20 (1~200)

**조건부 필수** (searchType에 따라):
- `searchType=KEYWORD` → `--search-keyword` 필수
- `searchType=COORDINATES` → `--req-lon`, `--req-lat` 필수

**선택**:
- `--page` 기본 1
- `--req-coord-type`, `--res-coord-type` 기본 WGS84GEO

### 예시

```bash
# 좌표로 강남구 찾기
python3 geofence.py spatial-search \
  --categories gu_gun --search-type COORDINATES \
  --req-lon 127.027621 --req-lat 37.497916 --pretty

# 키워드로 서울특별시 찾기
python3 geofence.py spatial-search \
  --categories city_do --search-type KEYWORD \
  --search-keyword "서울" --pretty
```

### 응답

```json
{
  "searchRegionsInfo": [
    {
      "regionInfo": {
        "regionId": "120822",
        "regionName": "강남구",
        "category": "gu_gun",
        "parentId": "21000",
        "description": "서울특별시 강남구",
        "properties": {
          "guName": "강남구",
          "doName": "서울특별시",
          "viewName": ""
        }
      }
    }
  ]
}
```

- `regionId`: `area` 서브커맨드에 넘길 ID
- `category`: 요청한 카테고리
- `parentId`: 상위 행정구역 (e.g., 시도)

## area: 영역 상세 조회

regionId로 해당 영역의 경계 폴리곤을 조회합니다.

**필수**:
- `--region-id` (spatial-search에서 얻은 ID, path parameter)

**선택**:
- `--res-coord-type` 기본 WGS84GEO

### 예시

```bash
# 강남구 경계 폴리곤
python3 geofence.py area --region-id 120822 --pretty
```

### 응답

GeoJSON FeatureCollection:
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [127.0397971, 37.5358249],
          [127.0460019, 37.5342731],
          ...
        ]]
      }
    }
  ]
}
```

경계 좌표는 WGS84GEO 기준의 lon/lat 쌍. 폴리곤의 꼭짓점이 많이 들어 있음.

## 용도

- **Point-in-Polygon 판정**: "내가 현재 강남구에 있는가?"
- **경계 시각화**: 특정 구역을 지도에 그리기
- **배달 가능 지역**: 서비스 영역 설정
- **행정구역별 통계 필터링**

## 워크플로우 예시

1. 사용자 좌표 → `spatial-search` (`COORDINATES`)로 소속 regionId 조회
2. regionId → `area`로 폴리곤 조회
3. 폴리곤으로 해당 지역의 범위 확인

## 주의사항

- 경계 폴리곤은 크므로 `--output-full /tmp/boundary.json`으로 파일 저장 권장
- `regionId`는 `spatial-search` 결과에서 얻는 문자열 (예: `120822`)
- `categories` 값은 **소문자**: `city_do`, `gu_gun`, `legalDong`, `adminDong`
- URL이 `/geofencing/search`가 아니라 **`/tmap/geofencing/regions`**
