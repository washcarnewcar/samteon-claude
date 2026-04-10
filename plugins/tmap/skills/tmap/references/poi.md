# POI 검색 (poi.py)

**Product: `base`** (TMap API 기본 상품)
**Status: Verified 2026-04-11** — 6개 서브커맨드 실제 API 테스트 통과

장소, 상점, 관광지 등 POI(Point Of Interest) 검색. 티맵은 약 150만 건의 POI 데이터를 보유.

## 서브커맨드

| 서브커맨드 | 목적 | 메서드 | 경로 |
|---|---|---|---|
| `search` | 키워드 통합검색 | GET | `/tmap/pois` |
| `detail` | POI ID로 상세 조회 | GET | `/tmap/pois/{poiId}` |
| `nearby-category` | 반경 내 업종별 검색 | GET | `/tmap/pois/search/around` |
| `around-route` | 경로 반경 검색 | POST | `/tmap/poi/findPoiRoute` |
| `admin-area` | 읍면동/도로명 조회 | GET | `/tmap/poi/findPoiAreaDataByName` |
| `region-code` | 지역분류코드 검색 | GET | `/tmap/poi/areascode` |

**주의**: `search`, `detail`, `nearby-category`는 `/tmap/pois/...`(복수형), 나머지는 `/tmap/poi/...`(단수형). 공식 API가 이렇게 나뉘어 있음.

## search: POI 통합검색

```bash
python3 poi.py search --keyword "스타벅스" --count 5 --pretty
python3 poi.py search \
  --keyword "카페" \
  --center-lat 37.5665 --center-lon 126.9780 \
  --radius 1 \
  --count 10 \
  --summarize standard --limit 5
```

파라미터:
- `--keyword` / `--searchKeyword` (필수)
- `--count` 기본 20 (1~200)
- `--page` 기본 1
- `--center-lat`, `--center-lon`, `--radius` (중심 기준 검색, km)
- `--search-type` (all/name/telno)
- `--search-typ-cd` (`A`=정확도, `R`=거리, R일 때 center 좌표 필수)
- `--req-coord-type`, `--res-coord-type`

응답 주요 필드:
```json
{"searchPoiInfo":{"totalCount":"81","count":"5","pois":{"poi":[{"id":"...","name":"스타벅스 ...","telNo":"...","frontLat":"37.x","frontLon":"126.x","upperAddrName":"서울","middleAddrName":"중구","roadName":"...","bizName":"커피전문점",...}]}}}
```

- `frontLat`/`frontLon`: 정문 좌표
- `noorLat`/`noorLon`: 중심 좌표
- `radius`: 중심에서 거리(km)
- `bizName`: 업종

## detail: POI 상세

```bash
python3 poi.py detail --poi-id 466860 --pretty
```

엔드포인트는 동적 path `/tmap/pois/{poiId}`. `--path` 비우면 자동 구성.

파라미터: `--poi-id` (필수), `--find-option`, `--res-coord-type`

응답: POI의 전체 상세 정보 (`poiDetailInfo`), 주소·전화·업종·시간 등 포함.

## nearby-category: 주변 카테고리 검색

```bash
python3 poi.py nearby-category \
  --center-lat 37.5665 --center-lon 126.9780 \
  --radius 1 --categories "편의점" --count 5 --pretty
```

필수:
- `--center-lat`, `--center-lon`
- `--radius` (km, 1~33)

선택:
- `--categories` 기본 "편의점". **한글 텍스트** (코드 아님). 여러 개는 세미콜론 `;` 구분
- `--page`, `--count`, `--multi-point`, `--sort` (price/distance/score)
- `--req-coord-type`, `--res-coord-type`

**카테고리 예시** (한글):
- `편의점`, `주유소`, `은행`, `ATM`, `약국`, `병원`, `카페`, `음식점`, `주차장`, `관공서`, `전기차충전소` 등

응답: `searchPoiInfo.pois.poi[]` 배열, 각 POI에 거리(`radius`) 포함.

## around-route: 경로 반경 POI

```bash
python3 poi.py around-route \
  --start-x 127.027926 --start-y 37.497952 \
  --end-x 126.977816 --end-y 37.566323 \
  --user-x 127.027926 --user-y 37.497952 \
  --line-string "127.027926,37.497952_126.977816,37.566323" \
  --keyword "주유소" --radius 5 --count 3 --pretty
```

**POST 요청**이며 다음이 body에 들어갑니다:
- `version: "1.0"` (문자열! query가 아님)
- `startX`, `startY`, `endX`, `endY` (필수)
- `userX`, `userY` (사용자 현재 좌표)
- `lineString` — 경로 좌표열 `"경도,위도_경도,위도..."` 형식 (**필수**)
- `searchType` (`keyword`|`category`|`around`) 기본 `keyword`
- `searchKeyword`
- `radius` (km)
- `count`, `page`
- `reqCoordType`, `resCoordType`

응답: `searchPoiInfo.pois.poi[]` with additional fields like `classCd`, `visitCountTotal`

## admin-area: 읍면동/도로명 조회

```bash
python3 poi.py admin-area --area-dong "역삼동" --pretty
```

파라미터:
- `--area-dong` (필수): 읍/면/동/리 또는 도로명 (예: "합정동", "세솔로")
- `--area-si-do`: 시/도 (선택, 예: "서울")
- `--address-type`: `addressName`, `roadName`, `all`
- `--count` 기본 10, `--page` 기본 1
- `--res-coord-type`

응답:
```json
{"findPoiAreaDataByNameInfo":{"totalCnt":"1","listCnt":"1","dongInfo":[{"address":"서울 강남구 역삼동","resLon":"127.03696201","resLat":"37.50068512"}]}}
```

## region-code: 지역분류코드 검색

```bash
python3 poi.py region-code --pretty
python3 poi.py region-code --area-typ-cd 02 --middle-cd-flag Y
```

파라미터 (모두 기본값 있음):
- `--area-typ-cd` 기본 `01` (`01`=행정, `02`=법정)
- `--large-cd-flag` 기본 `Y`
- `--middle-cd-flag` 기본 `N`
- `--small-cd-flag` 기본 `N`
- `--count` 기본 10 (10~8000), `--page` 기본 1

응답:
```json
{"areaCodeInfo":{"totalCnt":"17","listCnt":"10","poiAreaCodes":[{"areaDepth":"L","largeCd":"11","middleCd":"000","districtName":"서울"},...]}}
```

## 요약

- `--summarize [minimal|standard|full]` — POI 결과를 이름/주소/거리/좌표/전화 위주로 요약
- `--limit N` — 요약에 포함할 개수 제한

## 주의사항

- `search`는 전국 범위가 기본이라 결과가 산발적일 수 있음 → 중심 좌표 + radius로 제한 권장
- `nearby-category`의 categories는 **코드 아닌 한글 텍스트** 사용
- `around-route`는 복잡한 body 포맷 필요 — lineString을 반드시 포함해야 9401 오류 방지
- URL 경로가 `/tmap/pois/` (복수) vs `/tmap/poi/` (단수)로 섞여 있으므로 주의
