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

You orchestrate a thorough code review by combining automated checks with parallel **code-reviewer agents**, each bringing a different perspective. This catches issues that a single reviewer would miss.

## Process

### Phase 0: Detect Codex Availability

Determine whether to use Codex-powered reviews or fall back to agent-only mode.

**Step 1 — Check codex plugin install + codex CLI auth:**
```bash
test -f ~/.claude/plugins/marketplaces/openai-codex/plugins/codex/.claude-plugin/plugin.json && echo "plugin: installed" || echo "plugin: not installed"
test -s ~/.codex/auth.json && echo "auth: ok" || echo "auth: missing"
```

`~/.codex/auth.json`은 codex CLI 자체의 표준 인증 파일 위치이므로 codex 플러그인의 내부 계약에 의존하지 않는다. `test -s`로 파일 존재 + 크기 > 0을 함께 검사해 빈 파일을 인증된 것으로 오인하지 않게 한다. 파일 내용이 stale·invalid한 경우는 Phase 0에서 잡지 못하지만, Phase 4 Fallback rule이 실제 호출 실패를 잡아 해당 reviewer 자리만 LEGACY 에이전트로 대체한다.

**Step 2 — Determine mode and announce:**

| plugin | auth | Mode |
|---|---|---|
| installed | ok | **CODEX_MODE** |
| installed | missing | **LEGACY_MODE** (인증 미완료) |
| not installed | — | **LEGACY_MODE** (미설치) |

Announce:
- CODEX_MODE: `"Codex 플러그인 감지 + 인증 확인 → CODEX_MODE로 실행 (codex 위임 2개 + convention 에이전트)"`
- LEGACY_MODE (미설치): `"Codex 플러그인 미설치 → LEGACY_MODE로 실행 (code-reviewer 에이전트 3개 병렬)"`
- LEGACY_MODE (인증 미완료): `"Codex 플러그인 설치됨, 인증 미완료 → LEGACY_MODE로 실행"`

호출 메커니즘은 이 스킬에 못박지 않는다. CODEX_MODE에서 Phase 4 실행 시점에 사용 가능한 codex 진입점(서브에이전트, 슬래시 커맨드, 스킬 등) 중 적절한 것을 선택해 위임한다. Phase 4 도중 codex 호출이 실패한 경우의 처리는 Phase 4의 Fallback rule에 정의되어 있다.

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

3개 리뷰어를 **병렬**로 실행한다. Reviewer A·B는 codex 플러그인에 위임, Reviewer C는 feature:code-reviewer 에이전트.

위임 시 다음 두 가지를 prompt에 반드시 포함한다:

- `review-only — do not edit code, do not apply fixes`
- `complete the review in this turn — do not run in background`

또한 위임 prompt에는 "challenge whether the chosen design is the right one — question assumptions, point out where it could fail under real-world conditions" 같은 challenge 톤을 포함해 design adversarial 성격을 유지한다.

**Reviewer A — Bugs & Correctness (Codex 위임):**
```
Review-only delegation. Focus on:
- Logic errors and off-by-one mistakes
- Null/undefined handling gaps
- Race conditions and concurrency issues
- Error handling that swallows exceptions
- Edge cases not covered
- Security vulnerabilities (injection, XSS, etc.)

Challenge whether the chosen approach handles these robustly.

Changed files: [list from git diff]
Constraints: do not edit code, complete in this turn.

Report findings as: <file:line> — <severity: critical|warning|suggestion> — <issue>
```

**Reviewer B — Simplicity & DRY (Codex 위임):**
```
Review-only delegation. Focus on:
- Code duplication (same logic in multiple places)
- Unnecessary complexity (simpler approach exists)
- Over-engineering (abstractions that aren't needed yet)
- Dead code or unused imports

Challenge whether each abstraction earns its keep — design adversarial review,
not just defect spotting.

Changed files: [list from git diff]
Constraints: do not edit code, complete in this turn.

Report findings as: <file:line> — <severity: critical|warning|suggestion> — <issue>
```

**Reviewer C — Project Conventions (feature:code-reviewer agent):**
```
Review the code changes against these project rules:
[paste ALL discovered rules from Phase 1, especially critical/zero-tolerance items]

Check every rule against the actual code. Flag violations with exact file:line references.

Changed files: [list from git diff]
```

**Fallback rule** — codex 위임이 실패한 경우, **실패한 reviewer 자리만 LEGACY의 동등 에이전트로 대체**한다 (role-level 대체로 일관 처리):

- Reviewer A(Bugs & Correctness) 실패 → LEGACY Agent 2(Bugs & Correctness)로 대체
- Reviewer B(Simplicity & DRY) 실패 → LEGACY Agent 1(Simplicity & DRY)로 대체
- A·B 둘 다 실패하면 둘 다 대체

성공한 codex 결과는 그대로 활용한다. Reviewer C(convention)는 codex와 무관하게 항상 동일 동작이라 fallback 영향이 없다.

announce 예시:
- 하나만 실패: `"Codex Reviewer X 실패 → 해당 부분만 LEGACY 에이전트로 대체합니다."`
- 둘 다 실패: `"Codex 위임 모두 실패 → Reviewer A·B를 LEGACY 에이전트로 대체합니다."`

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
   - Codex 위임은 자유 텍스트로 응답한다. Reviewer prompt가 요청한 `<file:line> — <severity> — <issue>` 형식이 지켜지면 그대로 파싱.
   - **Severity 토큰이 응답에 있는 경우** — 키워드 매핑: `critical`/`high`/`severe` → 🔴 Critical, `warning`/`medium`/`moderate` → ⚠️ Warning, `suggestion`/`low`/`minor`/`nit` → 💡 Suggestion
   - **Severity 토큰이 없는 경우** — issue content에서 추론한다 (confidence filter를 이미 통과한 상태이므로 finding 자체는 신뢰 가능):
     - 보안 이슈, 논리 오류, race condition, null deref, 데이터 손실 가능성 → 🔴 Critical
     - 에러 처리 부재, 미커버 edge case, 잠재적 버그, 자원 누수 → ⚠️ Warning
     - unused import, 스타일, nit, 작은 중복, 네이밍 → 💡 Suggestion
     - content로도 추론이 어려울 만큼 모호하면 ⚠️ Warning (자동 수정 비용을 고려한 절충)
   - **응답 형식 불일치 처리**: 응답이 요청 형식을 따르지 않으면 best-effort로 file:line·severity 키워드를 추출. 추출 가능한 finding은 정상 처리. 추출 불가한 자유 텍스트 응답은 별도 ⚠️ Warning 항목 `Codex 응답 (형식 불일치)`로 보고하고 사용자가 직접 판단하도록 한다 (자동 분류 금지).
   - 각 finding의 source에 "(Codex)" suffix를 추가해 추적성 확보
   - Deduplicate: 두 Codex reviewer가 같은 file:line을 지적하면 더 높은 severity 유지

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

When the user chooses "수정해줘":

1. Fix all reported Critical and Warning issues
2. Announce: "수정이 완료되었습니다. 재검토를 시작하겠습니다."
3. **Re-run from Phase 4**: Launch reviewers again with the updated code
   - In CODEX_MODE: codex 위임 2개 + convention 에이전트를 다시 실행
     - 각 codex 위임 prompt 끝에 다음 문장을 append: `Also verify these previously reported issues are resolved: [issue list]`
   - In LEGACY_MODE: 3개 code-reviewer 에이전트 재실행
   - ALL reviewers receive: (a) the list of previously reported issues to verify resolution, (b) instruction to check for new issues introduced by the fixes
4. Consolidate results (Phase 5) and run build verification (Phase 6)
5. If new issues are found → present them → fix → **re-review again** (repeat this loop)
6. If no Critical/Warning issues remain → announce: "재검토 완료 — 모든 이슈가 해결되었습니다."

```
Fix → Re-review → More issues? → Fix → Re-review → Clean? → Done
```

This loop continues until either:
- No Critical or Warning issues remain
- The user explicitly chooses "이대로 진행" to accept remaining issues

**Never skip the re-review step.** If the user or the implementing agent fixes issues, always re-invoke this skill to verify the fixes.

## Communication

All user-facing content in Korean. Agent prompts in English.
Never use AskUserQuestion tool — communicate through normal text.
