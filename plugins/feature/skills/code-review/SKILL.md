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

**Step 1 — Locate the companion script:**
```bash
CODEX_SCRIPT=$(find ~/.claude/plugins/cache -path "*/codex/*/scripts/codex-companion.mjs" 2>/dev/null | sort -V | tail -1)
echo "codex-script: ${CODEX_SCRIPT:-not found}"
```

**Step 2 — Check readiness (only if script was found):**

If `$CODEX_SCRIPT` is empty → skip directly to LEGACY_MODE.

If found, run:
```bash
node "$CODEX_SCRIPT" setup --json 2>/dev/null || echo '{"ready":false,"error":"execution failed"}'
```

**Step 3 — Determine mode and announce:**

| Script found | `ready` | `auth.loggedIn` | Mode |
|---|---|---|---|
| No | — | — | LEGACY_MODE |
| Yes | false | — | LEGACY_MODE |
| Yes | true | false | LEGACY_MODE |
| Yes | true | true | CODEX_MODE |

Announce the result to the user:
- CODEX_MODE: `"Codex 감지 완료 → CODEX_MODE로 실행 (adversarial-review 2개 + convention 에이전트)"`
- LEGACY_MODE (not found): `"Codex 미설치 → LEGACY_MODE로 실행 (code-reviewer 에이전트 3개 병렬)"`
- LEGACY_MODE (not authenticated): `"Codex 설치됨, 인증 미완료 → LEGACY_MODE로 실행"`

Store `$CODEX_SCRIPT` for Phase 4 if CODEX_MODE.

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

Spawn 3 reviewers in parallel — 2 Codex adversarial-reviews via Bash + 1 convention agent:

**Reviewer A — Bugs & Correctness (Codex):**
```bash
node "$CODEX_SCRIPT" adversarial-review --wait "Focus on: logic errors, null/undefined handling gaps, race conditions, error handling that swallows exceptions, edge cases not covered, security vulnerabilities (injection, XSS), off-by-one mistakes"
```

**Reviewer B — Simplicity & DRY (Codex):**
```bash
node "$CODEX_SCRIPT" adversarial-review --wait "Focus on: code duplication (same logic in multiple places), unnecessary complexity (simpler approach exists), over-engineering (abstractions not needed yet), dead code and unused imports. Challenge whether each abstraction earns its keep."
```

**Reviewer C — Project Conventions (feature:code-reviewer agent):**
```
Review the code changes against these project rules:
[paste ALL discovered rules from Phase 1, especially critical/zero-tolerance items]

Check every rule against the actual code. Flag violations with exact file:line references.

Changed files: [list from git diff]
```

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

1. **Severity classification**:
   - **요구사항 미충족**: Plan requirement not implemented (from Phase 2)
   - **Critical**: Must fix — bugs, security issues, zero-tolerance rule violations
   - **Warning**: Should fix — quality issues, potential problems
   - **Suggestion**: Could fix — minor improvements, style preferences

2. **Confidence filter**: Only report issues where the reviewer is reasonably confident (vague "might be a problem" findings get filtered out)

3. **Codex output mapping** (CODEX_MODE only):
   - Codex adversarial-review returns structured findings with severity levels
   - Map: `critical`/`high` → 🔴 Critical, `medium` → ⚠️ Warning, `low` → 💡 Suggestion
   - Append "(Codex)" suffix to each finding's source for traceability
   - Deduplicate: if both Codex reviewers flag the same file:line, keep the higher severity

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
   - In CODEX_MODE: re-run both Codex adversarial-reviews + convention agent
     - Append to Codex focus text: "Also verify these previously reported issues are resolved: [issue list]"
   - In LEGACY_MODE: re-launch 3 code-reviewer agents
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

**Never skip the re-review step.** If the user or the implementing agent fixes issues and does not re-invoke this skill, the Stop hook will block the session from ending.

## Communication

All user-facing content in Korean. Agent prompts in English.
Never use AskUserQuestion tool — communicate through normal text.
