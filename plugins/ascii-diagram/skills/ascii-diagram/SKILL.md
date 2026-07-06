---
name: ascii-diagram
description: "Use when the user asks to draw a diagram, ERD, or architecture/structure sketch as text — '다이어그램 만들어줘', 'ERD 그려줘', '도식으로/구조도로 정리해줘', '관계도 보여줘' — rendered as terminal-style ASCII boxes directly in chat. Essential when labels contain Korean (한글: display width 2), which makes hand-aligned diagrams break. NOT for Figma/FigJam design tools or image-file generation — output is plain text in a code block."
allowed-tools: Bash, Read, Write
---

# ASCII 박스 다이어그램 (한글 폭 보정)

## Overview

ERD·아키텍처 도식을 터미널 스타일 ASCII 박스로 조립해 코드블록 텍스트로 전달한다.
한글·전각 문자는 표시 폭이 **2칸**이라 눈으로 공백 개수를 세서 줄을 맞추면 반드시 어긋난다.
`unicodedata.east_asian_width`로 폭을 계산하는 헬퍼(`box`/`cat`/`at`)로만 배치하면 한글이 몇 글자든 정렬이 맞는다.

**NOT for:** Figma/FigJam 다이어그램(→ Figma MCP), 이미지 파일 생성. 결과물은 텍스트다.

## 절대 규칙

- **손으로 칸 수를 세서 다이어그램을 직접 타이핑하지 않는다.** 한글 한 글자 들어가는 순간 어긋난다.
- 모든 줄은 `${CLAUDE_PLUGIN_ROOT}/scripts/diagram_lib.py`의 헬퍼로 생성한다.

## 사용 흐름

```bash
# 1) 조립 스크립트 작성 — diagram_lib 를 import 해서 print 로 출력
#    (예: /tmp/compose_diagram.py)

# 2) 실행
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 /tmp/compose_diagram.py

# 3) 출력 검증 — ▲·│ 세로 연결이 대상 박스의 컬럼 범위 안에 있는지 눈으로 확인

# 4) 결과를 ```text 코드블록에 담아 채팅으로 전달 (요청 시 .txt/.md 파일로 저장)
```

## 헬퍼 API

- `box(["제목", "내용1", "내용2"])` → 폭이 자동 계산된 박스 (줄 list). `w=`로 최소 폭 강제 가능
- `cat(박스A, [connector 줄들], 박스B)` → 가로로 나란히 결합. connector는 `["", "  fk_name", " ◀──────", "  부모 1 : 자식 N"]`처럼 줄 단위로 작성 (둘째 줄부터 박스 제목 줄 높이와 맞음)
- `at((5, "▲"), (66, "▲"))` → 5번·66번 표시컬럼에 절대 배치한 한 줄 생성. **컬럼 값은 `cat()` 출력을 찍어보고 대상 박스의 시작 컬럼을 실측**해서 정한다
- 세로 연결은 `at((컬럼, "▲"))` / `at((컬럼, "│ fk_name (부모 1 : 자식 N)"))` 줄을 연속으로 쌓는다

## 미니 예제

```python
from diagram_lib import box, cat, at

lines = []
lines += cat(box(["Branch  사업자", "본점/지점"]),
             ["", "  branch_id (@ManyToOne)", " ◀──────────────────────", "  사업자 1 : 차량 N"],
             box(["Vehicle  차량", "차량번호 · 상태"]))
lines += [at((20, "▲")), at((20, "│ vehicle_id (차량 1 : 이력 N)"))]
lines += box(["VehicleChangeHistory  변경이력", "  changeGroupId 로 동시수정 그룹핑"])
print("\n".join(lines))
```

```text
┌────────────────┐                        ┌─────────────────┐
│ Branch  사업자 │  branch_id (@ManyToOne)│ Vehicle  차량   │
│ 본점/지점      │ ◀──────────────────────│ 차량번호 · 상태 │
└────────────────┘  사업자 1 : 차량 N     └─────────────────┘
                    ▲
                    │ vehicle_id (차량 1 : 이력 N)
┌─────────────────────────────────────┐
│ VehicleChangeHistory  변경이력      │
│   changeGroupId 로 동시수정 그룹핑  │
└─────────────────────────────────────┘
```

## ERD 표기 규약

| 표기 | 의미 |
|---|---|
| `──▶` | `@ManyToOne` — **FK 컬럼을 들고 있는 쪽이 항상 N** |
| `─ ─ ─▶` | raw FK (JPA 연관 없이 ID만 보유) — 라벨에 `(raw FK)` 명시 |
| 카디널리티 | **"부모 1 : 자식 N" 형태로 통일** (예: `사업자 1 : 차량 N`). `N:1` 같은 자식-먼저 표기는 방향이 뒤집혀 보여서 금지 |
| `(0..1)` | nullable FK |
| `(hard)` | soft-delete 없는 엔티티 |
| `(→ ERD ②)` | 본체가 다른 장에 있는 참조 박스 |
| `★` | **문서·정책과 코드의 불일치 전용**. 단순 강조에 쓰면 불일치 표시와 혼동되므로 금지 |
| N:M | 중간 테이블 박스를 두고 양쪽 레그를 `(멤버십 N : 거래처 1)`처럼 분해 표기 + `⇒ A : B = N : M` 요약 줄 추가 |

## 함정 모음

1. **손으로 칸 수 세기 금지** — 한글 한 글자 들어가는 순간 끝. 모든 줄은 헬퍼로 생성.
2. **`cat()` 컬럼 폭 변동 주의** — connector 컬럼의 어떤 줄을 길게 바꾸면 컬럼 폭이 늘어 **우측 박스 전체가 밀린다**. 그 박스를 가리키는 `at()` 절대 좌표도 같이 갱신해야 한다.
3. **안전 기호만 사용** — 검증된 기호: `─ │ ┌ ┐ └ ┘ ▲ ▼ ◀ ▶ ★ ⇒ ↔ ·` 그 외 특수기호(예: `⚠`)는 환경에 따라 폭·글리프가 불안정하다.
4. **한 장에 박스 12개 이하** — 넘어가면 도메인별로 장을 나누는 게 가독성이 훨씬 좋다 (예: 기본정보 / 영업 / 배차 / 정산).
5. **(한계) 보는 쪽 폰트 의존** — 박스 문자(`─│┌┘`)는 Ambiguous width라 일부 CJK 터미널 폰트에서 2칸으로 그려져 미세하게 어긋나 보일 수 있다. 마크다운 코드블록(웹 UI·에디터)에서는 문제없다. 완벽한 픽셀 고정이 필요하면 글자별 좌표 PNG 렌더링으로 확장 가능(이 플러그인 범위 밖).
