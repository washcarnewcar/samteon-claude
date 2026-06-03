# self-improving-skills

복잡한 작업을 끝낼 때마다, 거기서 얻은 **재사용 가능한 기법을 자동으로 `SKILL.md`로 증류**하고 기존 스킬을 스스로 개선하는 자기개선 루프. Nous Research의 [Hermes Agent](https://github.com/NousResearch/hermes-agent)가 가진 "closed learning loop"를 Claude Code 플러그인 프리미티브(훅·서브에이전트·커맨드)로 이식한 것입니다.

> 한 세션에서 배운 것이 다음 세션의 자신에게 남습니다. 경험 → 증류 → 재사용.

## 동작 방식 (4층 루프)

| 층 | 구현 | 무엇을 하나 |
|---|---|---|
| **STORE** | `~/.claude/skills/<name>/SKILL.md` | 학습된 스킬을 전역 사용자 디렉토리에 누적. 플러그인 업데이트와 무관하게 지식이 쌓임 |
| **TRIGGER** | `Stop` 훅 (`distill-nudge.sh` → `analyze_turn.py`) | 마지막 증류 이후 도구 호출이 임계 이상 누적됐는데 아직 스킬화되지 않았으면, 종료를 한 번 막고 증류를 유도 |
| **REVIEW** | `skill-distiller` 서브에이전트 | 격리된 컨텍스트에서 `patch > umbrella수정 > 참조추가 > 신규생성` 우선순위로 판단해 SKILL.md를 쓰거나 고침 |
| **DISCOVER** | Claude Code 기본 동작 | 세션 시작 시 `skills/`를 자동 재스캔 → 새 스킬이 다음 세션 프롬프트에 자동 등장 |

부가:

- **TELEMETRY** (v0.2.0) — `Stop` 훅이 transcript에서 학습 스킬의 **사용 빈도를 추적**: `Skill` 호출→use, SKILL.md `Read`→view, `Write/Edit`→patch. `~/.claude/self-improve/skill_usage.json`에 use/view/patch 카운트 + 마지막 사용 시각 + `created_at` + `created_by`(agent/user)를 기록(atomic+flock, 세션별 offset으로 중복 방지). 이게 큐레이터가 "실제 안 쓰는 스킬"을 식별하는 데이터 기반입니다.
- **VALIDATE** — `PostToolUse` 훅이 학습 SKILL.md의 frontmatter·크기를 검증하고, 처음 만들어진 학습 스킬에 `metadata.provenance` 표시를 자동 부착 + usage 레코드 시딩(provenance 티어링: distiller=agent, 사용자 직접=user).
- **CURATE** (v0.3.0) — **시간기반 미사용 스킬 자동 정리**. `SessionStart` 훅이 큐레이션 주기(기본 7일)가 됐는지 확인하고, 됐으면 `curator_transitions.py`를 **인라인 자동 실행**: 마지막 활동(use/view/patch) 기준 **30일 미사용→stale, 90일→archive**(`.archive/` 로 이동, 삭제 아님). 변경 전 tar.gz 스냅샷을 뜨고, 다시 쓰이면 stale→active로 재활성화. **pin된 스킬과 사용자 작성(`created_by:user`) 스킬은 절대 건드리지 않음.** 의미 기반 중복 통합은 `/curate-skills`(LLM)가 담당. 커맨드: `/curator-status`(상태 조회), `/pin-skill`(보호), `/restore-skill`(복구).
- **수동 트리거** — `/distill-skill` 로 언제든 증류를 직접 실행.

## 흐름

```
복잡한 작업 종료
   │  Stop 훅: 마지막 증류 이후 도구호출 ≥ SIS_DISTILL_THRESHOLD 이고 파일편집 ≥ SIS_MIN_FILE_EDITS?
   ▼ (yes)
종료를 1회 block → "skill-distiller에 위임하라"
   ▼
skill-distiller 서브에이전트 (격리 컨텍스트)
   │  기존 스킬과 매칭 → patch  /  없으면 class-level 신규  /  일회성이면 skip
   ▼
~/.claude/skills/<name>/SKILL.md 작성·수정
   │  PostToolUse 훅: frontmatter 검증 + provenance 스탬프
   ▼
다음 세션 시작 → Claude Code가 자동 발견 → 스킬 재사용
```

## 설정 (환경변수)

| 변수 | 기본값 | 의미 |
|---|---|---|
| `SIS_DISTILL_THRESHOLD` | `12` | 증류 nudge를 띄울, 마지막 증류 이후 누적 도구 호출 수 |
| `SIS_MIN_FILE_EDITS` | `2` | nudge 조건: 마지막 증류 이후 실제 파일 편집(Edit/Write/MultiEdit) 최소 횟수. 순수 탐색·질의 턴은 트리거하지 않게 함 |
| `SIS_CURATE_MIN_SKILLS` | `8` | 자동 큐레이션을 시작하는 학습 스킬 수 |
| `SIS_CURATE_INTERVAL_DAYS` | `7` | 큐레이터 자동 실행 간격(일) |
| `SIS_STALE_AFTER_DAYS` | `30` | 마지막 활동 후 이 일수 미사용 시 stale 마킹 |
| `SIS_ARCHIVE_AFTER_DAYS` | `90` | 마지막 활동 후 이 일수 미사용 시 `.archive/` 로 이동 |

`~/.claude/settings.json` 의 `env` 블록이나 셸 환경에서 조정합니다.

## 설계 원칙 — dev-log의 실패에서 배운 가드레일

이 플러그인은 같은 마켓플레이스의 `dev-log` 훅이 **396개 실제 세션에서 단 한 번도 발동하지 않은** 원인 분석 위에 만들어졌습니다. 그 7대 실수를 모두 막았습니다:

1. **transcript를 실측 구조로 파싱.** 도구 호출은 `"name":"Edit"` (assistant 행의 `message.content[]` 안)으로 기록됩니다 — `"tool":"Edit"`가 아닙니다. `analyze_turn.py`는 실제 구조를 파싱합니다.
2. **"이미 했나"를 실제 행위로 판정.** 플러그인 이름 문자열(`grep -q`)이 아니라, skill-distiller로의 Task 위임 또는 `~/.claude/skills`의 SKILL.md 쓰기라는 실제 tool_use를 anchor로 봅니다. (substring 매칭은 플러그인 자기 이름이 transcript에 박혀 자기트립합니다.)
3. **임계값을 실데이터로.** 키워드 5회 같은 비현실적 게이트 대신, 누적 도구 호출·파일 편집 수라는 작업량 신호를 씁니다.
4. **Stop-hook 계약 준수.** block은 STDOUT + exit 0 의 `{"decision":"block","reason":...}` 로 emit합니다 (stderr+exit2 아님). `stop_hook_active` 루프 가드 포함.
5. **작업 유형 무관 트리거.** "빌드 에러 수정"처럼 좁은 조건(사용자 396세션 중 빌드 도구 호출 12회뿐)이 아니라, 모든 작업에 걸리는 기계적 복잡도 신호를 씁니다.
6. **situation-first 스킬 description.** distiller가 쓰는 SKILL.md는 방어적 "MUST ALWAYS"가 아니라 "이런 상황에 사용한다"는 상황 매칭으로 작성합니다.
7. **모델 자발성에만 의존하지 않음.** 훅이 강제하되, 그 훅이 정확하게 동작합니다. 동시에 어떤 에러에도 fail-safe로 approve(세션을 막지 않음).

## 한계 (정직하게)

- Hermes의 **무음·무료 데몬 스레드**(메인 대화 비용 0으로 백그라운드에서 스킬을 쓰는 fork)는 Claude Code에 대응물이 없습니다. 여기 격리 리뷰어는 서브에이전트라 **메인 턴에 빌링되고 사용자에게 보입니다.** 진짜 백그라운드를 원하면 launchd/cron `claude -p` 로 별도 구성해야 합니다.
- 프리픽스 캐시 상속, 런타임 ContextVar 기반 provenance도 이식 불가 → frontmatter 스탬프로 근사.
- 크로스세션 FTS5 검색(Hermes의 RECALL)은 이 플러그인 범위 밖입니다. 필요하면 `remember` 플러그인(메모리 자율 캡처)과 함께 쓰는 것을 권장.

## 구성 파일

```
self-improving-skills/
├── hooks/
│   ├── hooks.json            # Stop + SessionStart + PostToolUse 등록
│   ├── distill-nudge.sh      # Stop 래퍼 (fail-safe)
│   ├── session-init.sh       # SessionStart 래퍼
│   └── validate-skill.sh     # PostToolUse 래퍼
├── scripts/
│   ├── analyze_turn.py        # 복잡도 측정 + block/approve 결정 + usage 캡처
│   ├── usage_store.py         # 스킬 사용 telemetry 저장소 (atomic+flock)
│   ├── curator_transitions.py # 시간기반 stale→archive 상태머신 (+restore)
│   ├── curator_backup.py      # 변경 전 tar.gz 스냅샷
│   ├── session_init.py        # 자기개선 안내 + 큐레이터 자동 실행
│   └── validate_skill.py      # SKILL.md 검증 + provenance 스탬프 + usage 시딩
├── agents/
│   └── skill-distiller.md     # 격리 리뷰어 (patch>create 우선순위)
└── commands/
    ├── distill-skill.md       # 수동 증류 트리거
    ├── curate-skills.md       # 의미 기반 중복 통합 (LLM)
    ├── curator-status.md      # 루프 상태·사용 통계 조회
    ├── pin-skill.md           # 스킬 pin (자동 정리 보호)
    └── restore-skill.md       # 아카이브 복구
```
