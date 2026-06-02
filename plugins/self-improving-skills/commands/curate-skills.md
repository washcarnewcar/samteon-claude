---
description: 학습된 스킬 라이브러리(~/.claude/skills)를 정리한다 — 중복 통합, 오래된 스킬 아카이브
---

학습된 스킬 라이브러리를 검토하고 정리하세요. 이것은 자기개선 루프의 **유지보수 단계**입니다 (Hermes 큐레이터에 해당). 시간이 지나며 한 번에 하나씩 쌓인 스킬들을 class-level로 통합해, 라이브러리가 일회성 항목의 평평한 더미로 퇴화하지 않게 합니다.

## 절차

### 1. 학습 스킬 수집

```bash
ls -d ~/.claude/skills/*/ 2>/dev/null
grep -rl "provenance: self-improving-skills" ~/.claude/skills --include=SKILL.md 2>/dev/null
```

각 학습 스킬(`provenance: self-improving-skills` 표시가 있는 것)의 `name` 과 `description` 을 읽어 목록을 만드세요. **사용자가 직접 만든 스킬이나 다른 플러그인이 제공한 스킬은 건드리지 마세요** — provenance 표시가 있는 것만 큐레이션 대상입니다.

### 2. 중복·과편향 통합

같은 class를 다루는 스킬이 여러 개로 쪼개져 있으면 하나의 umbrella 스킬로 통합하세요:

- 가장 잘 명명된(class-level) 스킬을 기준으로 삼고, 나머지의 고유 내용을 그 SKILL.md 본문/`references/` 로 병합
- 통합으로 비게 된 스킬 디렉토리는 **삭제하지 말고** `~/.claude/skills/.archive/<name>/` 로 이동 (복구 가능하게)
- 통합 후 기준 스킬의 `description` 이 합쳐진 범위를 정확히 반영하도록 갱신

판단 기준: 두 스킬의 `description` 이 같은 상황에서 트리거될 만큼 겹치면 통합 후보입니다. 명확히 다른 도메인이면 그대로 둡니다.

### 3. 노후·저품질 스킬 아카이브

다음에 해당하면 `~/.claude/skills/.archive/` 로 이동(삭제 아님):

- 일회성 작업 서사로 보이거나 class-level이 아닌 이름(예: 특정 PR·버그·파일명에 묶인 것)
- 본문이 비었거나 frontmatter 가 깨진 것
- 명백히 틀렸거나 더 이상 유효하지 않은 내용(예: 이미 수정된 라이브러리 버전 한정 우회)

확신이 없으면 아카이브하지 말고 그대로 두세요. **절대 hard-delete 하지 않습니다** — 모두 `.archive/` 로 이동해 복구 가능하게 합니다.

### 4. 큐레이션 시각 기록

정리가 끝나면 다음 실행으로 마지막 큐레이션 시각을 기록하세요 (SessionStart 알림이 이 값을 보고 재권유 간격을 정합니다):

```bash
mkdir -p ~/.claude/self-improve
python3 -c "import json,time,os; open(os.path.expanduser('~/.claude/self-improve/curator_state.json'),'w').write(json.dumps({'last_run': time.time()}))"
```

### 5. 보고

무엇을 했는지 요약하세요: 통합한 스킬 쌍, 아카이브한 스킬, 그대로 둔 스킬 수. 변경이 없었다면 "정리할 것이 없었습니다"로 끝내세요.

$ARGUMENTS 가 주어지면 그 범위(예: 특정 도메인만 정리)에 집중하세요.
