# feature/code-review — 커밋된 변경을 리뷰할 때 대상 지정 방식 개선 제안

작성일: 2026-07-27
대상: `plugins/feature/skills/code-review/SKILL.md`
상태: 제안 (다른 세션에서 구현 예정)

## 요약

`code-review` 스킬은 리뷰 대상이 **아직 커밋되지 않았다는 것을 암묵적 전제**로 삼는다. 이미 커밋된 변경을 리뷰하려 하면 스킬 지침대로는 방법이 없어, 실사용에서 두 가지 사고가 났다.

1. 커밋을 워킹트리로 되돌리는 파괴적 우회를 하게 됨
2. codex 가 리뷰 대상을 스스로 고르면서 **엉뚱한 변경분을 리뷰**하고 "위반 없음" 을 반환

두 번째가 특히 위험하다. 리뷰를 돌렸는데 실제로는 아무것도 검토되지 않은 상태로 통과 처리될 수 있다.

해결은 간단하다. **리뷰 범위를 프롬프트로 전달하면 된다.** codex 는 에이전트라 저장소를 직접 탐색할 수 있다.

## 무엇이 문제인가

### 스킬의 현재 전제

`SKILL.md` 의 관련 서술이다.

- 142행: "`codex exec review` 는 default 로 working-tree 변경(changed or added files)을 자동 수집해 read-only 로 리뷰하므로, 메인이 changed files 리스트나 'do not edit' 제약을 prompt 로 강제할 필요가 없다."
- 144행: "**중요 — `--uncommitted` 같은 review-target 옵션은 사용 금지**" (PROMPT 와 mutually exclusive 라서)
- 378행: 재리뷰 시 "`codex exec review` 는 working-tree 변경분을 자동 수집하므로, **변경이 아직 커밋되지 않은 한** 첫 리뷰와 동일한 full 스코프가 유지된다"

즉 세 곳 모두 "리뷰 대상 = 워킹트리의 미커밋 변경" 을 전제한다. **커밋된 변경을 리뷰하는 경우에 대한 지침이 없다.**

### 실제로 벌어진 일

petel 프로젝트에서 기능 4개를 커밋한 뒤 리뷰를 돌리려 했다. 스킬대로면 방법이 없어서 다음을 했다.

```bash
git rev-parse HEAD          # 복구 지점 저장
git reset --soft <base>     # 커밋을 워킹트리로 되돌림
# 리뷰 실행
git reset --hard <저장한 SHA>  # 복구
```

**문제 1 — 파괴적이고 복구가 사람에게 달려 있다.** 리뷰 도중 세션이 끊기면 사용자는 커밋이 사라진 저장소를 보게 된다. 복구 SHA 를 대화에 남겨두는 것 말고는 안전장치가 없다.

**문제 2 — codex 의 대상 자동 선택이 일관되지 않았다.** 같은 조건에서 리뷰어 3개를 동시에 띄웠는데

| 리뷰어 | 실제로 본 것 |
| --- | --- |
| Simplicity | 의도한 변경분 (실제 결함 3건 발견) |
| Bugs | 의도한 변경분 (P1 포함 5건 발견) |
| Conventions | **머지되어 들어온 다른 브랜치 커밋** → "위반 없음" |

Conventions 결과 원문에 이렇게 적혀 있었다.

> I reviewed the actual change set in this worktree (the merged `codex/webrtc-probe` branch, commits `805c43c` + `b088a30`). The diff touches only `poc/webrtc_probe/`
> ...
> No convention violations or correctness bugs found.

메인이 이걸 그대로 받아 "Conventions 통과" 로 처리했다면, **컨벤션 검토를 아예 안 한 채 통과 처리**된다. 실제로 이후 대상을 명시해 재실행하니 다른 결과가 나왔다.

## 제안

### 핵심: 리뷰 범위를 프롬프트로 전달한다

`codex exec review` 는 단순 diff 도구가 아니라 **저장소를 탐색할 수 있는 에이전트**다. CLI 옵션 대신 프롬프트에 범위를 적으면 된다.

```
Review the changes in commits <base>..<head> of this repository (N commits, M files).
Run 'git diff <base>..<head>' yourself to see the full change set.
Do NOT review <제외할 경로> — that is already-merged history and not part of this change.

<기존 focus text>
```

이 방식의 이점이다.

- **파괴적 조작이 0** — 커밋을 건드리지 않는다
- **관점 3개 분리 유지** — PROMPT 를 계속 쓰므로 `--commit` 과 달리 Bugs/Simplicity/Conventions 를 나눌 수 있다
- **대상이 명시적** — codex 가 엉뚱한 걸 고를 여지가 없다
- **머지 커밋이 섞인 브랜치에서도 안전** — 제외 경로를 명시할 수 있다

실제로 이 방식으로 재실행했을 때 Conventions 리뷰어가 의도한 변경분을 정확히 리뷰했다.

### SKILL.md 수정 제안

**1) Phase 4 앞에 리뷰 대상 판별 단계를 추가한다**

```markdown
### Phase 3.5: 리뷰 대상 확정

리뷰 대상이 워킹트리에 있는지 커밋에 있는지 먼저 판별한다.

​```bash
git status --porcelain | head -1     # 미커밋 변경 유무
git log --oneline <base>..HEAD | wc -l   # 커밋된 변경 개수
​```

- **미커밋 변경이 대상**: 기존대로 default(working-tree 자동 수집)에 맡긴다.
- **커밋된 변경이 대상**: focus text 맨 앞에 범위 지시문을 붙인다. 커밋을 되돌리지 않는다.

  ​```
  Review the changes in commits <base>..HEAD of this repository (N commits, M files).
  Run 'git diff <base>..HEAD' yourself to see the full change set.
  Do NOT review <제외 경로> — that is already-merged history and not part of this change.
  ​```

  base 는 사용자에게 확인하거나 `git merge-base HEAD origin/<default-branch>` 로 정한다.

**리뷰 대상을 확보하려고 `git reset` 계열로 커밋을 되돌리지 않는다.** 세션이 중간에 끊기면 사용자가 커밋이 사라진 저장소를 보게 되고, 복구가 대화 기록에만 의존하게 된다.
```

**2) 144행의 금지 규정에 이유와 대안을 함께 적는다**

현재는 "옵션 사용 금지" 로 끝나 있어, 읽는 쪽이 "그럼 커밋된 변경은 리뷰 못 하나" 로 잘못 이해하기 쉽다.

```markdown
**`--uncommitted` / `--base` / `--commit` 같은 review-target 옵션은 사용 금지**: inline `[PROMPT]` 와 mutually exclusive 다
(`error: the argument '--uncommitted' cannot be used with '[PROMPT]'`). 관점 분리를 위해 PROMPT 가 필수이므로 옵션을 쓸 수 없다.

**대신 범위를 PROMPT 안에 적는다.** codex 는 저장소를 탐색할 수 있는 에이전트라 "이 커밋 범위를 보라, git diff 로 확인하라"
고 쓰면 그대로 따른다. CLI 옵션이 아니어도 대상 지정이 가능하다.
```

**3) 378행(재리뷰)의 전제를 고친다**

현재: "변경이 아직 커밋되지 않은 한 첫 리뷰와 동일한 full 스코프가 유지된다"

수정: 첫 리뷰에서 범위 지시문을 썼다면 재리뷰에도 **같은 지시문을 그대로** 넣는다. 수정 과정에서 새 커밋이 생겼으면 head 를 갱신한다.

**4) Phase 5 에 대상 검증을 추가한다**

리뷰 결과를 소비하기 전에 **그 리뷰어가 의도한 대상을 봤는지 확인한다.**

```markdown
각 `-o` 파일을 읽을 때, 리뷰어가 언급한 파일 경로가 실제 변경분과 겹치는지 확인한다.
겹치지 않으면 그 리뷰는 무효로 보고 범위를 명시해 재실행한다. "위반 없음" 이라는 결론이
엉뚱한 대상을 본 결과일 수 있다.
```

이 검증이 없으면 사고 2가 조용히 통과한다.

## 참고로 남기는 부수 발견

리뷰 자체와는 별개로, 같은 세션에서 **재리뷰 루프가 실제로 값을 했다.** 기록해둘 만하다.

- 1차 리뷰: 11건 발견
- 2차 재리뷰: 새로 10건. 그중 2건은 **1차 수정이 만들어낸 회귀**였다
  - 반응 지연을 고치려고 입력마다 대기를 버리게 했더니 캡처가 상한을 뚫음
  - 그걸 고치며 넣은 하한이 느린 장비에서 무력화됨
- 3차 재리뷰에서 또 새 건이 나왔다

"수정 후 반드시 재리뷰" 규정이 없었으면 회귀가 그대로 나갔을 것이다. 현행 규정이 옳다는 근거로 남긴다.

## 구현 범위

- `plugins/feature/skills/code-review/SKILL.md` 만 수정하면 된다
- 스킬 본문 수정이므로 `plugins/feature/.claude-plugin/plugin.json` 과 루트 `.claude-plugin/marketplace.json` 의 `version` 을 **같은 값으로 함께** 올린다 (AGENTS.md 배포 규칙)
