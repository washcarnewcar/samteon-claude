---
name: code-review
description: |
  Review code changes for quality, correctness, requirement fulfillment, and convention adherence using parallel code-reviewer agents.
  Use this skill when:
  - Code implementation (and optionally tests) are complete and need quality verification
  - User asks "review this code", "check my changes", "코드 리뷰해줘"
  - User says "look for bugs", "find issues", "문제 없는지 확인해줘"
  - The feature skill triggers the code-review phase
  - Before committing significant changes
  This skill goes beyond simple linting — it verifies requirements are met, finds related components
  that may need changes, and uses multiple independent reviewers for thorough coverage.
allowed-tools: Task, Bash, Glob, Grep, Read, Edit, TodoWrite, WebSearch
---

# Code Review

You orchestrate a thorough code review by combining automated checks with parallel reviewers, each bringing a different perspective. This catches issues that a single reviewer would miss.

## Process

### Phase 0: Detect Codex Availability

Determine whether to use Codex-powered reviews or fall back to agent-only mode.

**Step 1 — Check the codex CLI is installed and authenticated:**
```bash
command -v codex >/dev/null 2>&1 && echo "cli: installed" || echo "cli: not installed"
test -s ~/.codex/auth.json && echo "auth: ok" || echo "auth: missing"
```

This depends only on the `codex` CLI. `~/.codex/auth.json` is the codex CLI's standard auth file. `test -s` checks the file exists and is non-empty so an empty file is not mistaken for valid auth. A stale/invalid token is not caught here, but the Phase 4 Fallback rule catches the actual call failure and replaces only that reviewer slot with a LEGACY agent.

**Step 2 — Determine mode and announce:**

| codex CLI | auth | 동작 |
|---|---|---|
| installed | ok | **CODEX_MODE** |
| installed | missing | **사용자 확인 대기** (인증 미완료 — 자동 LEGACY 안 함) |
| not installed | — | **LEGACY_MODE** |

핵심 원칙: **Claude 에이전트(LEGACY)는 codex CLI가 미설치일 때만 쓴다.** codex가 설치돼 있으면 인증 미완료든 런타임 실패든 Claude로 조용히 내려가지 않는다.

Announce:
- CODEX_MODE: `"codex CLI 감지 + 인증 확인 → CODEX_MODE로 실행 (codex exec review 3개: Bugs / Simplicity / Conventions)"`
- LEGACY_MODE (미설치): `"codex CLI 미설치 → LEGACY_MODE로 실행 (code-reviewer 에이전트 3개 병렬)"`
- **인증 미완료 (설치됨 + auth missing)**: 자동으로 LEGACY로 가지 않는다. 사용자에게 알리고 선택을 기다린다 (이 스킬은 AskUserQuestion 금지 → 일반 텍스트로):
  ```
  codex CLI는 설치됐으나 인증이 안 돼 있습니다 (~/.codex/auth.json 없음).
  어떻게 진행할까요?
  1) codex 인증 후 CODEX_MODE로 진행 (예: codex login)
  2) LEGACY_MODE(Claude 에이전트 3개)로 진행
  ```
  사용자가 인증을 마쳤다고 하면 Phase 0 Step 1의 auth 체크를 재실행해 `auth: ok`를 확인한 뒤 CODEX_MODE로 진입한다. 사용자가 2)를 고르면 LEGACY_MODE로 진행한다.

CODEX_MODE에서 Reviewer A·B·C는 모두 메인 스킬이 직접 `Bash`로 `codex exec review`를 호출한다 (서브에이전트 위임 X).

### Phase 1: Discover Project Conventions

Read CLAUDE.md files (root and subdirectories) to build a dynamic checklist:

- **Critical rules**: Patterns explicitly marked as "금지", "forbidden", "zero tolerance", "필수"
- **Coding patterns**: Service layers, naming conventions, import policies
- **Build/lint commands**: What must pass before committing
- **Test policies**: What the project requires for test coverage

This checklist gets passed to the reviewer agents so they can validate project-specific rules without those rules being hardcoded in this skill.

### Phase 2: Verify Requirements

If a plan file exists (check `~/.claude/plans/` for the most recent `.md` file):

1. Read the plan and extract the list of planned tasks/changes
2. Run `git diff --name-only` to see what actually changed
3. For each planned task, verify it was implemented:
   - Read the relevant changed files
   - Confirm the implementation matches the requirement
4. Report any gaps as **"요구사항 미충족"** (highest severity)

If no plan file exists, skip this phase — the review focuses on code quality only.

### Phase 3: Check Related Components

For each changed file, search for potentially missed changes:

1. **Same directory, similar names**: Files in the same directory with similar naming patterns
   ```
   Example: Changed DraftGroupField.tsx → check for DraftField.tsx, DraftSpecField.tsx in same dir
   ```

2. **Same imports/dependencies**: Files that use the same hooks, services, DTOs, or utilities
   ```
   Example: Changed useDownloadDraft hook → find all files importing useDownloadDraft
   ```

3. **Report findings** as a table:
   ```
   | 상태 | 파일 | 이유 |
   |------|------|------|
   | ⚠️ 확인 필요 | SimilarComponent.tsx | 동일 훅 사용, 동일 디렉토리 |
   | ✅ 수정됨 | ChangedComponent.tsx | - |
   ```

Not every flagged file needs changing — this is a reminder to check, not an error report.

### Phase 4: Launch Reviewers

#### CODEX_MODE

Reviewer A·B·C 모두 메인 스킬이 직접 `Bash`로 `codex exec review`를 호출한다 (서브에이전트 위임 X). Reviewer C(Conventions)는 codex가 working-tree를 모르므로 Phase 1에서 추출한 프로젝트 규칙을 focus text(PROMPT)에 주입한다.

`codex exec review`는 default로 working-tree 변경(changed or added files)을 자동 수집해 read-only로 리뷰하므로, 메인이 changed files 리스트나 "do not edit" 제약을 prompt로 강제할 필요가 없다. focus text엔 review 관점만 담는다. 탐색을 토큰 절약을 위해 인위적으로 제한하지 않는다 — codex가 필요한 만큼 조사하게 둔다.

**중요 — `--uncommitted` 같은 review-target 옵션은 사용 금지**: codex CLI 0.133.0+ 부터 `--uncommitted` / `--base` / `--commit` 같은 review 대상 옵션은 inline `[PROMPT]` 와 mutually exclusive (`error: the argument '--uncommitted' cannot be used with '[PROMPT]'`). focus 차별화를 위해 PROMPT를 인자로 넘기는 본 스킬에서는 옵션을 빼고 default 동작(working-tree 자동 감지)에 맡긴다.

**Step 1 — 리뷰 결과를 받을 임시 디렉터리를 repo 밖에 만든다:**
```bash
mktemp -d
```
출력된 경로를 `REVIEW_DIR`로 쓴다. **반드시 repo working tree 밖**이어야 한다 — codex의 default review가 untracked 파일까지 리뷰 대상에 넣으므로, 리뷰 결과 파일을 repo 안에 두면 다른 reviewer가 그 파일을 변경분으로 오인해 리뷰한다.

**Step 2 — 한 응답 메시지에 다음 3개 tool call을 함께 발사 (진짜 병렬):**

`codex exec review`의 `-o <FILE>`는 codex의 **최종 리뷰 메시지만** 그 파일에 기록한다 — 탐색·도구호출 로그는 stdout으로만 흐르고 파일엔 안 들어간다. 메인은 stdout을 무시하고 `-o` 파일만 Read로 읽으면 깨끗한 리뷰 결과만 얻는다. (`<REVIEW_DIR>`는 Step 1에서 받은 실제 경로로 치환.)

```
Bash(
  command: `codex exec review -o "<REVIEW_DIR>/bugs.md" "<reviewer_a_focus>"`,
  description: "Codex review (Bugs)",
  run_in_background: true
)

Bash(
  command: `codex exec review -o "<REVIEW_DIR>/simplicity.md" "<reviewer_b_focus>"`,
  description: "Codex review (Simplicity)",
  run_in_background: true
)

Bash(
  command: `codex exec review -o "<REVIEW_DIR>/conventions.md" "<reviewer_c_focus>"`,
  description: "Codex review (Conventions)",
  run_in_background: true
)
```

Bash 3개는 자동 완료 알림 후 다음 턴에 각 `-o` 파일(`bugs.md` / `simplicity.md` / `conventions.md`)을 Read로 회수한다.

**Reviewer A focus text (Bugs & Correctness):**
```
Focus on bugs and correctness in this review:
- Logic errors and off-by-one mistakes
- Null/undefined handling gaps
- Race conditions and concurrency issues
- Error handling that swallows exceptions
- Edge cases not covered
- Security vulnerabilities (injection, XSS, etc.)

Challenge whether the chosen approach handles these robustly under real-world conditions.

Report findings as: <file:line> — <severity: critical|warning|suggestion> — <issue>
```

**Reviewer B focus text (Simplicity & DRY):**
```
Focus on simplicity and design quality in this review:
- Code duplication (same logic in multiple places)
- Unnecessary complexity (simpler approach exists)
- Over-engineering (abstractions that aren't needed yet)
- Dead code or unused imports

Challenge whether each abstraction earns its keep — design adversarial review,
not just defect spotting.

Report findings as: <file:line> — <severity: critical|warning|suggestion> — <issue>
```

**Reviewer C focus text (Project Conventions):**
codex는 working-tree 변경분은 자동 수집하지만 이 프로젝트의 고유 규칙은 모르므로, Phase 1에서 추출한 규칙을 focus text에 그대로 주입한다.
```
Focus on project convention adherence in this review.
Check the code changes against these project rules:
[paste ALL discovered rules from Phase 1, especially critical/zero-tolerance items]

Check every rule against the actual code. Flag violations with exact file:line references.

Report findings as: <file:line> — <severity: critical|warning|suggestion> — <issue>
```

**Codex 실패 처리 (CODEX_MODE — Claude 에이전트로 대체하지 않는다):**

codex 호출이 (a) Bash non-zero exit이거나 (b) `-o` 파일이 없거나 비어 있으면(codex가 최종 리뷰를 끝까지 못 낸 경우):

1. 해당 reviewer를 **1회 재시도**한다 (같은 `codex exec review` 명령 재실행).
2. 재시도 성공 → 그 `-o` 파일 결과를 정상 활용한다.
3. 재시도도 실패 → **Claude 에이전트로 대체하지 않는다.** 사용자에게 알리고 결정을 기다린다:
   - 실패한 reviewer 관점, 최초+재시도 2회 모두 실패한 사실, 원인 요약(stderr 또는 빈 출력)
   - 성공한 다른 reviewer 결과는 그대로 진행한다
   - 결정 대기: (1) 다시 재시도 (2) 해당 관점만 누락한 채 나머지 결과로 진행 (3) 중단

성공한 codex 결과(`-o` 파일)는 항상 그대로 활용한다.

announce 예시:
- 재시도: `"Codex Reviewer X 실패 → 1회 재시도합니다."`
- 재시도까지 실패: `"Codex Reviewer X 재시도까지 실패 (원인: <요약>). Claude로 대체하지 않습니다 — 다시 시도할지 / 이 관점 없이 나머지 결과로 진행할지 / 중단할지 알려주세요."`

#### LEGACY_MODE

Spawn 3 **feature:code-reviewer** agents in parallel, each with a different focus:

**Agent 1 — Simplicity & DRY:**
```
Review the code changes for:
- Code duplication (same logic in multiple places)
- Unnecessary complexity (simpler approach exists)
- Over-engineering (abstractions that aren't needed yet)
- Dead code or unused imports

Project conventions: [paste discovered rules from Phase 1]
Changed files: [list from git diff]
```

**Agent 2 — Bugs & Correctness:**
```
Review the code changes for:
- Logic errors and off-by-one mistakes
- Null/undefined handling gaps
- Race conditions or concurrency issues
- Error handling that swallows exceptions
- Edge cases not covered
- Security vulnerabilities (injection, XSS, etc.)

Changed files: [list from git diff]
```

**Agent 3 — Project Conventions:**
```
Review the code changes against these project rules:
[paste ALL discovered rules from Phase 1, especially critical/zero-tolerance items]

Check every rule against the actual code. Flag violations with exact file:line references.

Changed files: [list from git diff]
```

### Phase 5: Consolidate and Report

Combine findings from all sources:

1. **Confidence filter (가장 먼저 적용)**: vague "might be a problem" 류 추측 finding은 drop. 구체적 file:line이 있거나 명확한 issue 묘사가 있어야 통과.

2. **Severity classification** (confidence filter 통과한 finding 대상):
   - **요구사항 미충족**: Plan requirement not implemented (from Phase 2)
   - **Critical**: Must fix — bugs, security issues, zero-tolerance rule violations
   - **Warning**: Should fix — quality issues, potential problems
   - **Suggestion**: Could fix — minor improvements, style preferences

3. **Codex output mapping** (CODEX_MODE only):
   - 각 codex reviewer 결과는 `REVIEW_DIR`의 `-o` 파일(`bugs.md` / `simplicity.md` / `conventions.md`)에 있다 — codex의 최종 리뷰 메시지만 담긴 깨끗한 markdown이다. Read로 읽는다. stdout(진행 로그)은 무시한다.
   - **Severity 토큰이 응답에 있는 경우** — 키워드 매핑: `critical`/`high`/`severe` → 🔴 Critical, `warning`/`medium`/`moderate` → ⚠️ Warning, `suggestion`/`low`/`minor`/`nit` → 💡 Suggestion
   - **Severity 토큰이 없는 경우** — issue content에서 추론한다 (confidence filter를 이미 통과한 상태이므로 finding 자체는 신뢰 가능):
     - 보안 이슈, 논리 오류, race condition, null deref, 데이터 손실 가능성 → 🔴 Critical
     - 에러 처리 부재, 미커버 edge case, 잠재적 버그, 자원 누수 → ⚠️ Warning
     - unused import, 스타일, nit, 작은 중복, 네이밍 → 💡 Suggestion
     - content로도 추론이 어려울 만큼 모호하면 ⚠️ Warning (자동 수정 비용을 고려한 절충)
   - 각 finding의 source에 "(Codex)" suffix를 추가해 추적성 확보
   - Deduplicate: 여러 Codex reviewer가 같은 file:line을 지적하면 더 높은 severity 유지

4. **Present the report**:

```
## 코드 리뷰 결과

**전체 평가:** [1-2문장 요약]

---

### ❌ 요구사항 미충족
(Phase 2 결과, 해당 시)

### 🔴 Critical
- **파일**: file.kt:42
- **문제**: [구체적 설명]
- **해결**: [수정 방법]

### ⚠️ Warning
- ...

### 💡 Suggestion
- ...

### ✅ 잘한 점
- [긍정적 측면]

### 📋 연관 컴포넌트 확인
(Phase 3 결과)
```

### Phase 6: Build Verification

Run build/lint commands discovered from CLAUDE.md:
- Report pass/fail for each command
- If any fail, include the error output

### Phase 7: User Decision and Re-review Loop

Present findings and wait for the user's decision:
- **"수정해줘"** → Fix the issues, then **re-review** (see below)
- **"이대로 진행"** → Proceed as-is
- **"나중에"** → Note issues and move on

#### Re-review after fixes

**CRITICAL**: Fixing issues without re-review is prohibited. Every fix round MUST be followed by a re-review.

**재리뷰 스코프 원칙 (가장 중요)**: 재리뷰는 **첫 리뷰와 정확히 동일한 풀 스코프**로 수행한다. "내가 수정한 부분이 잘 적용됐는지"만 확인하는 좁은 점검이 **아니다.** 재리뷰의 1순위 목적은 변경분 전체를 *마치 처음 보는 것처럼* 다시 리뷰해서, **첫 리뷰에서 미처 발견하지 못한 기존 이슈까지 찾아내는 것**이다. 이전 이슈 해결 검증과 수정으로 인한 새 이슈 점검은 그 위에 *추가로* 얹는 부차 작업일 뿐, 재리뷰 스코프를 거기로 좁히면 안 된다. (재리뷰가 수정 검증만 하다 첫 리뷰가 놓친 버그를 계속 못 잡는 회귀를 막기 위한 규칙.)

When the user chooses "수정해줘":

1. Fix all reported Critical and Warning issues
2. Announce: "수정이 완료되었습니다. 변경분 전체를 처음부터 다시 검토하겠습니다."
3. **Re-run from Phase 4 — 변경분 전체를 첫 리뷰와 동일하게 full re-review**: 수정된 코드를 *마치 처음 보는 것처럼* 첫 리뷰와 동일한 reviewer 구성(Bugs / Simplicity / Conventions)·동일한 변경 스코프로 처음부터 다시 리뷰한다.
   - In CODEX_MODE: `codex exec review` 3개(Bugs / Simplicity / Conventions)를 다시 실행한다. `codex exec review`는 working-tree 변경분을 자동 수집하므로, 변경이 아직 커밋되지 않은 한 첫 리뷰와 동일한 full 스코프가 그대로 유지된다 — focus text의 review 관점도 첫 리뷰와 동일하게 쓴다. 결과는 **새 임시 디렉터리**(`mktemp -d` 재실행) 또는 새 파일명(예: `bugs-round2.md` / `simplicity-round2.md` / `conventions-round2.md`)에 받아 이전 라운드 결과를 덮지 않게 한다.
     - 각 reviewer focus text 끝에 다음 문장을 append (full re-review가 주, 이전 이슈 검증은 부차임을 명시): `This is a FULL re-review with the same scope as the first pass. Independently re-examine ALL of the changed code and surface every issue you find, including ones the first pass may have missed — do NOT narrow your review to the fixed lines. As a secondary check only, also confirm these previously reported issues are resolved: [issue list]`
   - In LEGACY_MODE: 3개 code-reviewer 에이전트를 첫 리뷰와 동일한 focus·동일한 변경 스코프로 재실행한다.
   - ALL reviewers receive, **in this priority order**:
     - **(a) [1순위] 변경분 전체를 첫 리뷰와 동일 스코프로 처음부터 다시 리뷰** — 첫 리뷰가 놓쳤을 수 있는 기존 이슈를 새로 발굴하는 것이 주목적
     - (b) [부차] the list of previously reported issues to verify resolution
     - (c) [부차] check for new issues introduced by the fixes
4. Consolidate results (Phase 5) and run build verification (Phase 6)
5. If new issues are found → present them → fix → **re-review again** (repeat this loop)
6. If no Critical/Warning issues remain → announce: "재검토 완료 — 모든 이슈가 해결되었습니다." 그리고 이 리뷰 사이클에서 만든 `REVIEW_DIR`(들)을 `rm -rf`로 정리한다.

```
Fix → Re-review → More issues? → Fix → Re-review → Clean? → Done
```

This loop continues until either:
- No Critical or Warning issues remain
- The user explicitly chooses "이대로 진행" to accept remaining issues

**Never skip the re-review step, and never narrow it to a fix-verification pass.** If the user or the implementing agent fixes issues, always re-invoke this skill and run a full re-review at the same scope as the first pass — verifying the fixes is only a secondary check on top of that.

## Communication

All user-facing content in Korean. Agent prompts in English.
Never use AskUserQuestion tool — communicate through normal text.
