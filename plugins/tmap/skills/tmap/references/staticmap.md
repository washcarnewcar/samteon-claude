# 정적 지도 이미지 (staticmap.py)

**Product: `base`** (TMap API 기본 상품)
**Status: Verified 2026-04-11** — 실제 API 호출 성공, PNG 이미지 80KB 저장 확인

특정 위치의 정적 지도 이미지(PNG/JPG)를 생성. 사용자에게 지도 이미지를 파일로 제공해야 할 때 사용.

## 서브커맨드

| 서브커맨드 | 메서드 | 경로 |
|---|---|---|
| `render` | GET | `/tmap/staticMap` |

**주의**: `/tmap/staticImage`가 아닌 **`/tmap/staticMap`** (대문자 M)

## 필수 파라미터

- `--longitude` — 중심 경도 (**`centerLat/centerLon` 아님**)
- `--latitude` — 중심 위도
- `--output PATH` — 저장할 파일 경로

## 선택 파라미터 (기본값 있음)

- `--zoom` 기본 15 (6~19 유효)
- `--width` 기본 512 (1~512 px)
- `--height` 기본 512 (1~512 px)
- `--format` 기본 PNG (PNG 또는 JPG)
- `--markers` — 마커 좌표 (예: `"126.978155,37.566371"`)
- `--coord-type` 기본 WGS84GEO

## 응답

바이너리 이미지 → `--output` 경로에 저장. stdout에는 저장 결과 JSON:
```json
{"savedTo": "/tmp/map.png", "bytes": 80471}
```

## 예시

```bash
# 서울시청 중심 지도
python3 staticmap.py render \
  --longitude 126.978 --latitude 37.5665 \
  --zoom 15 --width 512 --height 512 \
  --output /tmp/seoul_city_hall.png

# JPG 포맷, 다른 줌
python3 staticmap.py render \
  --longitude 127.0276 --latitude 37.4979 \
  --zoom 13 --width 400 --height 300 \
  --format JPG --output /tmp/gangnam.jpg

# 마커 포함
python3 staticmap.py render \
  --longitude 126.978 --latitude 37.5665 \
  --zoom 14 --markers "126.978155,37.566371" \
  --output /tmp/with_marker.png
```

## 주의사항

- 파라미터 이름이 다른 TMap API(`centerLat/centerLon`)와 다름. **`longitude`/`latitude`** 사용
- 이미지는 바이너리라 반드시 `--output <path>`로 파일 저장. stdout에는 경로만 출력
- `format` 값은 **대문자** `PNG`/`JPG` (소문자도 스크립트 내부에서 변환되지만 API는 대문자 요구)
- `width`/`height` 최대 512
- 이미지 응답이 JSON이면 에러 (에러 메시지 확인)
