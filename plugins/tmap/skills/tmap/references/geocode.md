# 지오코딩 (geocode.py)

**Product: `base`** (TMap API 기본 상품)
**Status: Verified 2026-04-11** — 8개 서브커맨드 실제 API 테스트 통과

주소 ↔ 좌표 변환 및 좌표계 변환.

## 서브커맨드 요약

| 서브커맨드 | 목적 | 메서드 | 경로 |
|---|---|---|---|
| `forward` | 구조화 주소(시도+구군+동+번지) → 좌표 | GET | `/tmap/geo/geocoding` |
| `full` | 전체 문자열 주소 → 좌표 | GET | `/tmap/geo/fullAddrGeo` |
| `reverse` | 좌표 → 주소 | GET | `/tmap/geo/reversegeocoding` |
| `convert` | 좌표계 변환 (WGS84GEO ↔ KATECH 등) | GET | `/tmap/geo/coordconvert` |
| `address` | 주소 변환 (지번↔도로명) | GET | `/tmap/geo/convertAddress` |
| `near-road` | 좌표 → 가까운 도로 매칭 | GET | `/tmap/road/nearToRoad` |
| `postal` | 주소 → 우편번호 | GET | `/tmap/geo/postcode` |
| `reverse-label` | 좌표 → 지역 레이블 | GET | `/tmap/geo/reverseLabel` |

## 어떤 서브커맨드를 쓸지

- 사용자가 **"서울역"** 같은 짧은 키워드 → `full` (또는 POI 검색 `poi.py search`)
- **"서울특별시 중구 세종대로 110"** 같은 전체 주소 → `full`
- **"서울특별시 / 중구 / 세종대로 / 110"** 처럼 필드가 분리됨 → `forward`
- **위도/경도** 숫자 → `reverse`
- 다른 좌표계(KATECH, EPSG3857 등) → `convert`
- 지번 ↔ 도로명 상호 변환 → `address`
- GPS 좌표를 가장 가까운 도로 위로 스냅 → `near-road`

## 공통 파라미터

- `--version 1`
- `--format json` (기본)
- `--path` — 엔드포인트 경로 덮어쓰기 (TMap 경로 변경 대비)
- `--json '{...}'` — 임의 쿼리 파라미터 병합
- `--pretty` — stdout JSON 들여쓰기
- `--output-full PATH` — 전체 원본 응답을 파일로 저장

## 좌표계 값

- `WGS84GEO` (기본, 표준 경위도)
- `KATECH` (한국 표준, **KATEC 아님 — H 붙음**)
- `EPSG3857` (Web Mercator)
- `BESSELGEO`
- `GRS80`

## forward: 구조화 주소 → 좌표

```bash
python3 geocode.py forward \
  --city-do "서울특별시" --gu-gun "중구" --dong "태평로1가" --bunji "31" \
  --pretty
```

파라미터: `--city-do`, `--gu-gun`, `--dong`, `--bunji`, `--address-flag`, `--coord-type`

응답:
```json
{"coordinateInfo":{"coordType":"WGS84GEO","addressFlag":"F01","matchFlag":"M11","lat":"37.566573","lon":"126.978205","city_do":"서울","gu_gun":"중구",...}}
```

## full: 전문자 지오코딩

```bash
python3 geocode.py full --full-addr "서울특별시 중구 세종대로 110" --pretty
```

파라미터: `--full-addr` (필수), `--coord-type`

응답: 여러 후보가 `coordinate` 배열에 들어옴. `newLat`/`newLon`은 정확한 좌표, `newBuildingName` 등 포함.

## reverse: 좌표 → 주소

```bash
python3 geocode.py reverse --lat 37.5665 --lon 126.9780 --pretty
```

파라미터: `--lat`, `--lon` (필수), `--address-type` (A00=도로명/A10=지번 등)

응답:
```json
{"addressInfo":{"fullAddress":"서울특별시 중구 태평로1가 31","addressType":"A02","city_do":"서울특별시","gu_gun":"중구","legalDong":"태평로1가","bunji":"31",...}}
```

## convert: 좌표계 변환

```bash
python3 geocode.py convert --from-coord WGS84GEO --to-coord KATECH --lat 37.5665 --lon 126.9780
```

파라미터: `--from-coord`, `--to-coord` (필수), `--lat`, `--lon`

응답:
```json
{"coordinate":{"lat":"552074.351684","lon":"309911.6786"}}
```

**주의**: `KATEC`이 아니라 `KATECH`(H 포함)입니다.

## address: 지번 ↔ 도로명

```bash
python3 geocode.py address --req-add "서울특별시 중구 세종대로 110" --pretty
```

파라미터:
- `--req-add` (필수): 요청 주소
- `--search-typ-cd` 기본 `NtoO` (도로명→지번), `OtoN` (지번→도로명)
- `--req-multi`, `--res-coord-type`

응답:
```json
{"ConvertAdd":{"resCount":"1","resMulti":"S","reqAddress":"N","upperDistName":"서울","middleDistName":"중구","legalLowerDistName":"태평로1가","adminDistName":"태평로1가",...}}
```

## near-road: 좌표 → 가까운 도로

```bash
python3 geocode.py near-road --lat 37.5665 --lon 126.9780 --pretty
```

GPS 스냅 용도. 좌표에서 가장 가까운 도로(링크) 정보 반환.

응답:
```json
{"resultData":{"header":{"laneType":1,"tollLink":0,"speed":10,"roadName":"일반도로","linkId":"61478","totalDistance":93,"lane":1,...}}}
```

## postal: 주소 → 우편번호

```bash
python3 geocode.py postal --addr "서울시 중구 태평로1가" --pretty
```

파라미터:
- `--addr` (필수): 주소 문자열 (**`--full-addr`가 아닙니다**)
- `--address-flag`, `--page`, `--count`, `--coord-type`

응답: 매칭된 주소들의 좌표와 우편번호

## reverse-label: 좌표 → 지역 레이블

```bash
python3 geocode.py reverse-label --center-lat 37.5665 --center-lon 126.9780 --pretty
```

파라미터:
- `--center-lat`, `--center-lon` (필수, `--lat`/`--lon` 아님!)
- `--req-level` 기본 15 (15~19 유효)
- `--req-coord-type`, `--res-coord-type`

응답: 해당 좌표가 속한 POI/지역 레이블
```json
{"poiInfo":{"id":"40189","name":"서울특별시청","poiLat":37.56670018296471,"poiLon":126.97840390417564}}
```

## 주의사항

- 지오코딩은 정확한 매칭을 보장하지 않습니다. 주소가 모호하면 여러 후보 중 첫 번째가 반환될 수 있음
- POI 검색(`poi.py search`)과 혼동하지 말 것. 지오코딩은 **주소**를 좌표로, POI 검색은 **장소명**을 좌표로 변환
- 공식 좌표계 이름은 `KATECH` (H 포함). `KATEC`은 허용되지 않음
- `convert` 엔드포인트는 `addressConvert`와 다르며, 좌표계 간 변환 전용
