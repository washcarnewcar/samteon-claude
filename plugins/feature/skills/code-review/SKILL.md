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
allowed-tools: Task, Bash, Glob, Grep, Read, Edit, Write, TodoWrite, WebSearch
---

# Code Review

You orchestrate a thorough code review by combining automated checks with parallel reviewers, each bringing a different perspective. This catches issues that a single reviewer would miss.

## Process

### Phase 0: Detect Codex Availability

Determine whether to use Codex-powered reviews or fall back to agent-only mode.

**Step 1 — Check the codex CLI, authentication, and review-ledger runtime:**
```bash
command -v codex >/dev/null 2>&1 && echo "cli: installed" || echo "cli: not installed"
test -s ~/.codex/auth.json && echo "auth: ok" || echo "auth: missing"
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "python: ok"
else
  echo "python: missing-or-too-old"
fi
```

CODEX_MODE depends on the `codex` CLI and Python 3.9+ (standard library only) for its durable review ledger and two-file persistence helper. `~/.codex/auth.json` is the codex CLI's standard auth file. `test -s` checks the file exists and is non-empty so an empty file is not mistaken for valid auth. A stale/invalid token is not caught here, but the Phase 4 failure rule catches the actual call failure, retries once, and surfaces a repeated failure to the user without silently switching to a LEGACY agent.

**Step 2 — Determine mode and announce:**

| codex CLI | auth | Python 3.9+ | 동작 |
|---|---|---|---|
| installed | ok | ok | **CODEX_MODE** |
| installed | missing | — | **사용자 확인 대기** (인증 미완료 — 자동 LEGACY 안 함) |
| installed | ok | missing/old | **사용자 확인 대기** (ledger runtime 미완료 — 자동 LEGACY 안 함) |
| not installed | — | — | **LEGACY_MODE** |

핵심 원칙: **Claude 에이전트(LEGACY)는 codex CLI가 미설치일 때만 쓴다.** codex가 설치돼 있으면 인증 미완료든 런타임 실패든 Claude로 조용히 내려가지 않는다.

Announce:
- CODEX_MODE: `"codex CLI, 인증, Python 3.9+ 확인 → CODEX_MODE로 실행 (codex exec review 3개: Bugs / Simplicity / Conventions)"`
- LEGACY_MODE (미설치): `"codex CLI 미설치 → LEGACY_MODE로 실행 (code-reviewer 에이전트 3개 병렬)"`
- **인증 미완료 (설치됨 + auth missing)**: 자동으로 LEGACY로 가지 않는다. 사용자에게 알리고 선택을 기다린다 (이 스킬은 AskUserQuestion 금지 → 일반 텍스트로):
  ```
  codex CLI는 설치됐으나 인증이 안 돼 있습니다 (~/.codex/auth.json 없음).
  어떻게 진행할까요?
  1) codex 인증 후 CODEX_MODE로 진행 (예: codex login)
  2) LEGACY_MODE(Claude 에이전트 3개)로 진행
  ```
  사용자가 인증을 마쳤다고 하면 Phase 0 Step 1의 auth 체크를 재실행해 `auth: ok`를 확인한 뒤 CODEX_MODE로 진입한다. 사용자가 2)를 고르면 LEGACY_MODE로 진행한다.
- **Python 미설치/구버전 (codex installed + auth ok)**: durable ledger와 최종 피드백 기록을 생략한 채 CODEX_MODE를 시작하지 않는다. Python 3.9+ 설치 또는 명시적인 LEGACY_MODE 선택을 기다린다.

CODEX_MODE에서 Reviewer A·B·C는 모두 메인 스킬이 직접 `Bash`로 `codex exec review`를 호출한다 (서브에이전트 위임 X).

#### CODEX_MODE review-cycle state

Use the packaged helper CLI for lifecycle validation and atomic state updates. Do not hand-edit `state.json`, import the helper through an ad-hoc Python wrapper, or reimplement its transitions in shell code:

```bash
FEATURE_REVIEW_REPO_ROOT="$(git rev-parse --show-toplevel)"
FEATURE_REVIEW_GIT_DIR="$(git rev-parse --absolute-git-dir)"
REVIEW_CYCLE_DIR="$FEATURE_REVIEW_GIT_DIR/feature-code-review-state"
REVIEW_STATE_FILE="$REVIEW_CYCLE_DIR/state.json"
REVIEW_FEEDBACK_HELPER="${CLAUDE_PLUGIN_ROOT}/scripts/review_feedback.py"
REVIEW_CYCLE_ID="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
```

- The helper state schema records `cycle_id`, repo/task identity, initial HEAD, approved paths, current phase/pending action, round, reviewer slot attempts/jobs/outputs, requirement gaps, findings, and the exact completed-review snapshot.
- Store it only at the working-tree-external `<absolute-git-dir>/feature-code-review-state/state.json`. Initialize with `python3 "$REVIEW_FEEDBACK_HELPER" init --repo "$FEATURE_REVIEW_REPO_ROOT" --scope-json '<stable task/scope JSON>' --cycle-id "$REVIEW_CYCLE_ID"`; the helper validates the exact Git-directory location, creates it exclusively with mode-0600 state, and never overwrites an existing cycle. Preserve this generated id with the task context; on resume use that exact id rather than adopting the id from whatever ledger may later occupy the path.
- Resume with `python3 "$REVIEW_FEEDBACK_HELPER" resume --state "$REVIEW_STATE_FILE" --cycle-id "$REVIEW_CYCLE_ID" --scope-json '<same JSON>'`. Repo equality alone is invalid. The returned `action` is authoritative. For `run-reviewers`, use its `launch_slots` and `collect_slots` plus per-slot status, attempt, and job id; never assume every slot already has a job. `reconcile-launches` means at least one durable launch reservation may already have started an external job: never relaunch it automatically, recover and attach the existing job id or explicitly verify that no process remains before recording that attempt as failed. `consolidate-round` means Phase 5 still needs explicit empty-or-populated result recording. Waits do not increment a round, terminal-pending state goes directly to Phase 8, and a `complete` state returns to `persist-feedback` only when this cycle's transaction artifacts still need verified cleanup.
- Apply every mutation with `python3 "$REVIEW_FEEDBACK_HELPER" state --state "$REVIEW_STATE_FILE" --cycle-id "$REVIEW_CYCLE_ID" --action <action> [action arguments]`. Pass the exact initialized cycle id on every call; a stale command must fail instead of mutating a replacement ledger at the same path. Available actions are `begin-round`, `reserve-launches`, `slot-running`, `slot-success`, `slot-failure`, `await-reviewer`, `retry-reviewer`, `waive-reviewer`, `round-reviewed`, `record-gaps`, `record-findings`, `consolidate-round`, `reopen-consolidation`, `amend-finding-metadata`, `apply-decisions`, `await-user`, `prepare-rereview`, `abort`, and `finalize`. JSON ledger actions take `--payload-json`; reviewer attach/result actions also require the exact reserved `--attempt`.
- A successful reviewer slot must have its exact non-empty `round-N/<slot>.md` regular file; `slot-success` records its helper-verified SHA-256 and `round-reviewed` rechecks every output. `prepare-rereview` is the only way to approve the complete post-fix path set without incrementing the round. The helper rejects HEAD, Git-index, unapproved path-scope, and reviewed-content drift.
- An `aborted` state is never auto-resumed. `abort` is rejected while any reviewer job is `launching` or `running`; reconcile, wait for, or terminate every possibly active background job and record its result first. After the user explicitly chooses to abandon the cycle, run `python3 "$REVIEW_FEEDBACK_HELPER" discard --state "$REVIEW_STATE_FILE" --cycle-id "$REVIEW_CYCLE_ID" --reason '<reason>'`; never delete the directory ad hoc. For `complete`, obey `resume`: if it returns `persist-feedback`, rerun the exact persist command to verify the two targets and finish artifact cleanup; only a complete state with no artifacts can use the same guarded `discard` command.
- Store no secrets, credentials, personal data, or raw tool logs in the state file. This state is an execution ledger, not project guidance.
- In LEGACY_MODE, do not create this state because Phase 8 does not persist LEGACY feedback.

### Phase 1: Discover Project Conventions

Read both AGENTS.md and CLAUDE.md files (root and relevant subdirectories) to build a dynamic checklist:

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
In CODEX_MODE, store verified gaps in `state.json.requirement_gaps` separately from Codex findings; they participate in the terminal gate but are never converted into Codex review learnings.

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

**Step 1 — 현재 라운드의 결과 디렉터리를 review-cycle state 아래에 만든다:**

Run the helper CLI with `state --action begin-round`. It captures the current repository snapshot, succeeds only for `pending_action: launch-round`, verifies HEAD/index/approved paths, increments exactly once, saves the state atomically, and exclusively creates `<REVIEW_CYCLE_DIR>/round-<N>/` as `ROUND_DIR`. If a previous process stopped between creating an empty round directory and saving state, the helper reclaims only that exact empty directory; a nonempty, symlink, or non-directory path fails closed. A retry, running-job recovery, or decision wait never runs `begin-round`. Do not overwrite a completed earlier round directory.

**Step 2 — 실행 의도를 먼저 저장한 뒤, 한 응답 메시지에 다음 3개 tool call을 함께 발사 (진짜 병렬):**

외부 프로세스를 시작하기 전에 현재 `launch_slots` 전체를 한 번의 원자적 전이로 예약한다. 아래 배열은 첫 라운드 예시이며, 재개나 재시도에서는 `resume`이 반환한 정확한 slot 배열로 바꾼다.

```bash
python3 "$REVIEW_FEEDBACK_HELPER" state --state "$REVIEW_STATE_FILE" --cycle-id "$REVIEW_CYCLE_ID" --action reserve-launches --payload-json '["bugs","simplicity","conventions"]'
```

응답의 각 slot `attempt`를 보존한 뒤에만 아래 Bash 호출을 실행한다. 예약 뒤 중단되면 상태는 `launching`이며 resume은 `reconcile-launches`를 반환한다. 이 상태를 `launch_slots`처럼 다시 실행하지 않는다.

`codex exec review`의 `-o <FILE>`는 codex의 **최종 리뷰 메시지만** 그 파일에 기록한다 — 탐색과 도구 호출 로그는 stdout으로만 흐르고 파일엔 안 들어간다. 메인은 stdout을 무시하고 `-o` 파일만 Read로 읽으면 깨끗한 리뷰 결과만 얻는다. (`<ROUND_DIR>`는 Step 1에서 확정한 실제 경로로 치환.)

```
Bash(
  command: `codex exec review -o "<ROUND_DIR>/bugs.md" "<reviewer_a_focus>"`,
  description: "Codex review (Bugs)",
  run_in_background: true
)

Bash(
  command: `codex exec review -o "<ROUND_DIR>/simplicity.md" "<reviewer_b_focus>"`,
  description: "Codex review (Simplicity)",
  run_in_background: true
)

Bash(
  command: `codex exec review -o "<ROUND_DIR>/conventions.md" "<reviewer_c_focus>"`,
  description: "Codex review (Conventions)",
  run_in_background: true
)
```

Bash 3개는 자동 완료 알림 후 다음 턴에 `ROUND_DIR`의 각 `-o` 파일(`bugs.md` / `simplicity.md` / `conventions.md`)을 Read로 회수한다.

각 background job id를 받은 즉시 해당 slot에 `state --action slot-running --slot <slot> --attempt <reserved-attempt> --job-id <id>`를 실행한다. 완료 후에는 `-o` 파일을 확인하고 성공이면 `state --action slot-success --slot <slot> --attempt <reserved-attempt>`, 실패 또는 빈 출력이면 `state --action slot-failure --slot <slot> --attempt <reserved-attempt>`을 실행한다. `launching` 상태의 실패는 해당 프로세스가 시작되지 않았거나 이미 종료됐음을 확인한 뒤에만 기록한다. Resume 시에는 `launch_slots`만 새로 예약하고 시작하며, `collect_slots`의 기존 job만 회수하고, `launching_slots`는 먼저 reconcile한다. 오래되거나 생략된 attempt는 거부된다. 세 slot이 모두 `completed` 또는 명시적으로 `waived`가 된 뒤에만 `state --action round-reviewed`를 실행한다.

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

The second `slot-failure` automatically stores `pending_action: await-reviewer-decision`; a normal third launch reservation is rejected. `state --action await-reviewer --slot <failed-slot>` remains an idempotent assertion before yielding. Option (1) runs `state --action retry-reviewer --slot <slot>`, reserves only that slot with `reserve-launches`, then launches and attaches the exact new attempt, option (2) runs `state --action waive-reviewer --slot <slot> --reason '<reason>'`, and option (3) first reconciles every `launching` slot and waits for or terminates every `running` reviewer before recording each result, then runs `state --action abort --reason '<reason>'`. The aborted cycle is retained until an explicit guarded `discard`. None of these paths silently creates a new round.

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
   - 각 codex reviewer 결과는 현재 `ROUND_DIR`의 `-o` 파일(`bugs.md` / `simplicity.md` / `conventions.md`)에 있다 — codex의 최종 리뷰 메시지만 담긴 깨끗한 markdown이다. Read로 읽는다. stdout(진행 로그)은 무시한다.
   - **Severity 토큰이 응답에 있는 경우** — 키워드 매핑: `critical`/`high`/`severe` → 🔴 Critical, `warning`/`medium`/`moderate` → ⚠️ Warning, `suggestion`/`low`/`minor`/`nit` → 💡 Suggestion
   - **Severity 토큰이 없는 경우** — issue content에서 추론한다 (confidence filter를 이미 통과한 상태이므로 finding 자체는 신뢰 가능):
     - 보안 이슈, 논리 오류, race condition, null deref, 데이터 손실 가능성 → 🔴 Critical
     - 에러 처리 부재, 미커버 edge case, 잠재적 버그, 자원 누수 → ⚠️ Warning
     - unused import, 스타일, nit, 작은 중복, 네이밍 → 💡 Suggestion
     - content로도 추론이 어려울 만큼 모호하면 ⚠️ Warning (자동 수정 비용을 고려한 절충)
   - 각 finding의 source에 "(Codex)" suffix를 추가해 추적성 확보
   - Deduplicate only by a stable root-cause finding id. The same file:line may carry distinct findings and must never be merged merely by location.

4. **Maintain a Codex feedback ledger (CODEX_MODE only)**:
   - After every review round, add each Codex finding that passed the confidence filter **and was verified against the code by the main skill** to `state.json`. A Codex claim is not durable feedback until that verification succeeds.
   - Track every verified severity in the execution ledger, but classify `reusable` separately for **all** severities. Set `reusable: true` only when the root cause supports a concrete future project or module rule; a one-off Critical/Warning fix is not automatically durable, and a Suggestion may be durable when it captures a real convention.
   - Submit verified entries with `state --action record-findings --payload-json '<JSON array>'`; the helper merges only the same stable root-cause id across reviewers and re-review rounds. Each submitted item identifies exactly the current completed round in `source_rounds`; the helper owns merging prior rounds. Preserve the first concrete evidence and update the disposition as the cycle progresses. Submit the independently verified Phase 2 list with `record-gaps` rather than mixing it into Codex findings.
   - Every finding includes `id`, `scope`, `issue`, `rule`, `severity`, `disposition`, `reusable`, and `source_rounds`. Before recording any `reusable: true` finding, also inspect the root `AGENTS.md` and `CLAUDE.md` and include `review_date` plus exact coverage for both targets: `{"kind":"managed"}` or `{"kind":"external","anchor":"<exact unique text>","label":"<short label>"}`. This metadata is Phase 5 input, not something added after finalization.
   - Use explicit dispositions: `open`, `해결됨`, `사용자 수용`, `보류`, `제안됨`, or `false-positive`. Keep resolved findings in the ledger even when the final re-review is clean; otherwise the learning that prevented the regression would be lost.
   - Mark a finding `false-positive` when later evidence disproves it; Phase 8 must exclude it. Do not add positive comments, raw reviewer output, requirement-check results, build failures, or vague risks rejected by the confidence filter.
   - The CLI saves and validates the updated `state.json` **before** presenting the report or yielding for a user decision, so a skill re-invocation or context compaction resumes the same ledger and round history.
   - Always call both `record-gaps` and `record-findings` for every completed round, using `[]` when that source is clean. Then run `state --action consolidate-round`. Until both empty-or-populated payloads are recorded and consolidation succeeds, resume remains at `consolidate-round`, user decisions and `finalize` are prohibited, and Codex feedback cannot be silently skipped after context compaction.

5. **Present the report**:

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

Run build/lint commands discovered from AGENTS.md and CLAUDE.md:
- Report pass/fail for each command
- If any fail, include the error output

### Phase 7: User Decision and Re-review Loop

Present findings. When the terminal gate still has a requirement gap or Critical/Warning finding, wait for the user's decision:
- **"수정해줘"** → Keep affected requirement gaps and Critical/Warning findings `open`, fix them, then **re-review** (see below)
- **"이대로 진행"** → Mark remaining requirement gaps and Critical/Warning findings `사용자 수용`, then proceed as-is
- **"나중에"** → Mark remaining requirement gaps and Critical/Warning findings `보류`, then move on

Wait for a user decision whenever a requirement gap or Critical/Warning finding remains. If none remain, the cycle may finish without waiting solely on Suggestions. Mark **every** verified, unapplied Suggestion `제안됨` regardless of `reusable`; reuse classification affects only Phase 8 selection, never lifecycle completion. Do not describe an unapplied Suggestion as resolved.

Immediately before yielding for that decision, run `state --action await-user`. On resume, submit an explicit id-to-disposition object with `state --action apply-decisions --payload-json '<JSON object>'`. Apply the choice to requirement gaps and Critical/Warning findings; Suggestions independently end as `해결됨`, `제안됨`, or `false-positive` rather than inheriting an accept/defer decision meant for blockers.

The helper accepts `해결됨` for a Critical/Warning Codex finding only after a later round in which all three reviewer slots produced completed outputs; a waived perspective is not full-review evidence. `사용자 수용` and `보류` remain explicit no-fix terminal choices. Every blocker terminal disposition must pass through `apply-decisions` in the current consolidated round, which records decision provenance. Do not bypass this gate by putting a final disposition directly in `record-findings`; `finalize` rechecks both provenance and later full-review evidence independently.

#### Re-review after fixes

**CRITICAL**: Fixing issues without re-review is prohibited. Every fix round MUST be followed by a re-review.

**재리뷰 스코프 원칙 (가장 중요)**: 재리뷰는 **첫 리뷰와 정확히 동일한 풀 스코프**로 수행한다. "내가 수정한 부분이 잘 적용됐는지"만 확인하는 좁은 점검이 **아니다.** 재리뷰의 1순위 목적은 변경분 전체를 *마치 처음 보는 것처럼* 다시 리뷰해서, **첫 리뷰에서 미처 발견하지 못한 기존 이슈까지 찾아내는 것**이다. 이전 이슈 해결 검증과 수정으로 인한 새 이슈 점검은 그 위에 *추가로* 얹는 부차 작업일 뿐, 재리뷰 스코프를 거기로 좁히면 안 된다. (재리뷰가 수정 검증만 하다 첫 리뷰가 놓친 버그를 계속 못 잡는 회귀를 막기 위한 규칙.)

When the user chooses "수정해줘":

1. Fix all reported requirement gaps and Critical/Warning issues
2. Announce: "수정이 완료되었습니다. 변경분 전체를 처음부터 다시 검토하겠습니다."
3. **Re-run Phase 2, then Phase 4 — 요구사항 재검증 + 변경분 전체 full re-review**: 먼저 Phase 2를 다시 실행해 requirement gaps를 갱신한다. 이어 수정된 코드를 *마치 처음 보는 것처럼* 첫 리뷰와 동일한 reviewer 구성(Bugs / Simplicity / Conventions), 동일한 변경 스코프로 처음부터 다시 리뷰한다.
   - In CODEX_MODE: 기존 `REVIEW_CYCLE_DIR/state.json`에서 같은 `cycle_id`와 ledger를 복원하고 `state --action prepare-rereview`를 실행해 `phase: re-review`, `pending_action: launch-round`를 저장한 뒤 Phase 4로 간다. 이 전이는 현재 repository snapshot을 직접 캡처하여 수정 과정에서 추가된 경로까지 다음 full review 스코프로 명시 승인하지만 HEAD 변경은 거부한다. Phase 4만 `round`를 정확히 한 번 증가시키고 새 `ROUND_DIR`에서 `codex exec review` 3개(Bugs / Simplicity / Conventions)를 실행한다. `codex exec review`는 working-tree 변경분을 자동 수집하므로, 변경이 아직 커밋되지 않은 한 첫 리뷰와 동일한 full 스코프가 유지된다 — focus text도 동일하게 쓴다. 완료된 이전 round 디렉터리나 ledger를 덮어쓰지 않는다.
     - 각 reviewer focus text 끝에 다음 문장을 append (full re-review가 주, 이전 이슈 검증은 부차임을 명시): `This is a FULL re-review with the same scope as the first pass. Independently re-examine ALL of the changed code and surface every issue you find, including ones the first pass may have missed — do NOT narrow your review to the fixed lines. As a secondary check only, also confirm these previously reported issues are resolved: [issue list]`
   - In LEGACY_MODE: 3개 code-reviewer 에이전트를 첫 리뷰와 동일한 focus·동일한 변경 스코프로 재실행한다.
   - ALL reviewers receive, **in this priority order**:
     - **(a) [1순위] 변경분 전체를 첫 리뷰와 동일 스코프로 처음부터 다시 리뷰** — 첫 리뷰가 놓쳤을 수 있는 기존 이슈를 새로 발굴하는 것이 주목적
     - (b) [부차] the list of previously reported issues to verify resolution
     - (c) [부차] check for new issues introduced by the fixes
4. Consolidate results (Phase 5) and run build verification (Phase 6)
5. If new issues are found → present them → fix → **re-review again** (repeat this loop)
6. If no requirement gaps or Critical/Warning issues remain → verified fixes are marked `해결됨`, every unapplied Suggestion is marked `제안됨`, and announce: "재검토 완료 — 요구사항 미충족이 없고 모든 Critical/Warning 이슈가 해결되었습니다."

```
Fix → Re-review → More issues? → Fix → Re-review → Clean? → Done
```

This loop continues until either:
- No requirement gaps and no Critical or Warning issues remain
- The user explicitly chooses "이대로 진행" to accept remaining requirement gaps or issues
- The user explicitly chooses "나중에" to defer remaining requirement gaps or issues

Before entering Phase 8, run `state --action finalize`. It requires a final disposition for every requirement gap and finding, enforces evidence from at least one all-completed full-review round later than each resolved blocker's last source round, captures the repository again, and verifies that HEAD, Git index, approved paths, and working-tree content exactly match the completed-review snapshot. It then validates every selected finding's persistence schema and builds both root-document candidates read-only, including managed blocks, external anchors, UTF-8, and cross-target history agreement, before atomically saving `persist-feedback` state. If this preflight rejects only `review_date` or `coverage`, run `state --action amend-finding-metadata --payload-json '[{"id":"...","review_date":"YYYY-MM-DD","coverage":{...}}]'` and retry finalize; this preserves the finding's real source rounds and decision provenance. For other current-round ledger corrections, use `reopen-consolidation`, record both arrays again, reconsolidate, and reapply dispositions. Do not hand-edit state or invent a new source round. Phase 8 may resume this exact `cycle_id` after context compaction; it must not start a new review round or cycle.

**Never skip the re-review step, and never narrow it to a fix-verification pass.** If the user or the implementing agent fixes issues, always re-invoke this skill and run a full re-review at the same scope as the first pass — verifying the fixes is only a secondary check on top of that.

### Phase 8: Persist Codex Review Learnings

Run this phase **only after the whole review/re-review cycle reaches a terminal state** in Phase 7. Writing guidance earlier is prohibited because `codex exec review` would treat the modified guidance files as new working-tree changes in the next full re-review.

#### 적용 조건과 입력 준비

1. **CODEX_MODE**에서만 실행한다. LEGACY_MODE에서는 기록을 건너뛰고 Codex 피드백이 없었다고 알린다.
2. reviewer 재시도, 사용자 결정, 중단 상태에서는 아무것도 쓰지 않는다. 기존 `REVIEW_CYCLE_DIR/state.json`을 정확한 `cycle_id`와 scope로 `resume`하고, 반환된 action이 `persist-feedback`인지 확인한다. 정상 최초 반영은 `phase: persist-feedback`, `pending_action: persist-feedback`, `status: terminal-pending-persistence`여야 한다. 단, 두 target 반영과 state 완료 기록 뒤 artifact 정리 전에 중단된 복구에서는 `phase: complete`, `pending_action: none`, `status: complete`이면서 같은 cycle의 검증 가능한 transaction artifact가 남아 있어 `resume`이 `persist-feedback`을 반환하는 상태도 허용한다.
3. 기록 대상은 `select_persistable_findings`가 고른 항목뿐이다. 즉, 메인 스킬이 실제 코드에서 검증했고 `reusable: true`이며 최종 disposition이 `{해결됨, 사용자 수용, 보류, 제안됨}` 중 하나인 Codex finding만 포함한다. `open`, `false-positive`, 요구사항 점검 결과, 빌드 실패, 긍정 코멘트, 검증되지 않은 추측은 제외한다.
4. Phase 5에서 ledger에 저장한 각 finding의 다음 정보를 다시 확인한다. 이 단계에서 새 필드를 준비하거나 terminal ledger를 수정하지 않는다.
   - 안정적인 root-cause `id`, 영향받는 경로 또는 모듈 `scope`, 한 줄짜리 미래 예방 규칙 `rule`, Codex 리뷰 날짜, 최종 disposition
   - `AGENTS.md`와 `CLAUDE.md` 각각의 `coverage`
   - 같은 의미의 명시적 규칙이 해당 파일의 managed section 밖에 없으면 `kind: managed`를 쓴다.
   - 이미 같은 의미의 명시적 규칙이 밖에 정확히 한 번 있으면 `kind: external`과 그 규칙을 유일하게 식별하는 정확한 `anchor`, 사람이 읽을 짧은 `label`을 쓴다. 이 경우 헬퍼는 규칙 본문을 중복하지 않고 날짜와 disposition이 남는 메타데이터 참조 entry를 managed section에 만든다.
5. raw Codex 출력, 비밀, 자격 증명, 개인정보, 줄 번호에만 해당하는 일회성 수정, 근거 없이 프로젝트 전체로 일반화한 규칙을 넣지 않는다. 두 파일의 외부 규칙이 의미상 같은지는 메인 스킬이 실제 문맥을 읽고 판단하며, 헬퍼의 정확한 anchor 검사는 그 판단을 대신하지 않는다.
6. 선택된 finding이 없으면 두 파일을 그대로 두고 기록할 지속 가능한 피드백이 없었다고 보고한다.

헬퍼가 생성하고 관리하는 section 형식은 다음과 같다. 숨은 ID와 규칙 해시는 같은 root cause를 갱신하고 중복을 차단하기 위한 계약이므로 직접 만들거나 수정하지 않는다.

```markdown
## Codex 코드 리뷰에서 배운 규칙

<!-- feature:codex-review-learnings:start -->
- **`path/or/module/**`**: [미래 구현에서 지킬 구체적인 규칙]. (Codex 리뷰 YYYY-MM-DD, 해결됨) <!-- feature:codex-review-id:<stable-id>;kind:rule;rule:<sha256>;anchor:- -->
<!-- feature:codex-review-learnings:end -->
```

#### 검증된 반영 실행

`AGENTS.md`나 `CLAUDE.md`를 `Edit` 또는 `Write`로 직접 수정하지 않는다. 준비된 ledger를 원자적으로 저장한 뒤 아래 명령만 실행한다.

```bash
python3 "$REVIEW_FEEDBACK_HELPER" persist --state "$REVIEW_STATE_FILE" --cycle-id "$REVIEW_CYCLE_ID"
```

이 명령은 다음 계약을 코드로 강제한다.

- 현재 HEAD와 guidance 두 파일을 제외한 최종 리뷰 working-tree fingerprint가 그대로인지 재검증한다. Guidance 파일은 중단된 이전 persistence와 사용자의 동시 문서 편집을 복구하고 보존하기 위해 현재 bytes에서 다시 candidate를 만든다.
- 저장소 루트의 정확한 `AGENTS.md`와 `CLAUDE.md`만 대상으로 삼고, 파일이 없으면 만들며 symlink나 비정규 파일은 거부한다.
- 정식 제목과 marker 쌍을 파싱하고 partial, reversed, duplicate, unknown managed entry를 fail closed로 거부한다. 숨은 stable ID와 규칙 해시로 기존 entry를 갱신하며, 다른 ID가 같은 규칙을 소유하면 중복으로 거부한다.
- 두 파일을 먼저 읽어 complete candidate를 만들고 mode를 보존한 결정적 same-directory `.candidate` artifact를 flush한다. 새 파일 mode는 `0644`다. 두 candidate의 stable ID와 규칙 해시 순서가 다르면 한쪽의 과거 기록을 추측하지 않고 중단한다. 같은 경로에 예상 bytes와 다른 candidate가 이미 있으면 외부 파일로 간주해 삭제하거나 덮어쓰지 않고 중단한다.
- state-directory 잠금 아래에서 현재 target을 같은 디렉터리의 결정적 `.original` artifact로 먼저 이동해 mutation 경계의 실제 bytes와 mode를 검증한다. 그 뒤 candidate를 hard link로 no-clobber publish하므로, 마지막 검사 뒤 다른 파일이 나타나도 덮어쓰지 않는다.
- 첫 파일 이동 또는 publish 뒤 프로세스가 끝나거나 두 파일 반영 뒤 state 완료 기록 전에 끝나도, 같은 `cycle_id`의 정확한 `.candidate`, `.original`, `.rollback` 조합을 재분류해 이어서 완료한다. 다른 working-tree 경로의 최종 리뷰 snapshot은 그대로여야 한다.
- 두 번째 publish나 최종 검증이 실패하면 target을 삭제하지 않고 결정적 `.rollback` 경로로 atomic no-replace 이동한 다음 자신의 candidate인지 검증한다. 일치할 때만 원래 bytes와 mode를 복원하고 `.rollback`을 정리한다. 사용자가 그 사이 바꾼 target이면 no-clobber 방식으로 원위치에 돌려놓으며, 복원할 수 없으면 사용자 파일과 transaction artifact를 보존한 partial state로 명시적으로 오류 처리한다. 이 과정 중 중단돼도 다음 실행이 검증된 `.original` 또는 parked target을 복구한다.
- 두 target 검증과 같은 lock 안에서 state를 `complete`로 기록한 뒤 이번 `cycle_id`의 정확한 artifact만 정리한다. `.original`과 `.rollback`을 `.candidate`보다 먼저 정리하므로 어느 cleanup 지점에서 중단되어도 재실행할 수 있다. 복구 시 `.original`은 내용이 검증된 같은 cycle의 `.candidate`가 함께 있을 때만 트랜잭션 소유 아티팩트로 인정하며, 단독 파일은 보존하고 실패한다. 이미 같은 candidate이면 verified no-op으로 취급한다.

명령이 실패하면 `state.json`과 모든 round 출력을 보존하고 정확한 오류를 보고한다. 수동으로 한쪽 파일만 보정하거나 성공했다고 말하지 않는다. Snapshot 또는 guidance 충돌을 안전하게 복원하거나 `reopen-consolidation`으로 보정할 수 없고 transaction artifact가 하나도 없는 terminal-pending cycle은, 사용자가 피드백 기록 포기를 명시적으로 승인한 경우에만 exact cycle id와 reason을 넣은 guarded `discard`로 폐기할 수 있다.

#### 보고와 범위 제한 정리

1. 명령의 JSON 결과를 읽어 어떤 규칙이 갱신되었거나 이미 동일했는지와 두 대상 파일을 보고한다. 두 파일의 transactional publish 또는 verified no-op이 모두 성공한 때만 피드백을 저장했다고 말한다.
2. `persist` 명령은 두 파일의 검증이 모두 성공하거나 기록할 항목이 없는 경우에만 state를 `complete`로 바꾼다.
3. Run `resume` once more before cleanup. If it returns `persist-feedback`, rerun `persist` because verified transaction artifacts remain; if it rejects the artifact-free complete cycle as already complete, run the guarded `discard --state ... --cycle-id ... --reason 'completed review cleanup'` command. The helper re-resolves the Git directory, validates repo/cycle/status, rejects remaining transaction artifacts, and removes only that exact cycle. If persistence, verification, discard, or any safety check fails, retain the state and all round outputs for recovery and report the exact failure.

## Communication

All user-facing content in Korean. Agent prompts in English.
Never use AskUserQuestion tool — communicate through normal text.
