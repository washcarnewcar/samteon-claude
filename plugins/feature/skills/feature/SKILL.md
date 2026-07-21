---
name: feature
description: |
  Orchestrate feature development with built-in quality gates: test writing and code review.
  Use this skill when:
  - User asks to implement a new feature or make significant code changes
  - User says "add X feature", "implement Y", "build Z functionality"
  - User runs /feature command
  - Any task that involves writing new code or modifying existing code substantially
  This skill ensures that every implementation includes automated test writing and code review
  as mandatory final steps, preventing untested or unreviewed code from being committed.
  Even if the user doesn't explicitly ask for tests or review, activate this skill to ensure quality.
---

# Feature Development with Quality Gates

You are orchestrating feature development. Claude Code's built-in plan mode handles the exploration, design, and implementation phases naturally. Your role is to ensure **test writing, code review, and durable Codex feedback recording happen after implementation** — these are the steps that most often get skipped.

## How This Works

Claude Code already excels at:
- Understanding requirements (conversation + plan mode)
- Exploring codebases (Explore agents, Glob, Grep, Read)
- Designing architecture (Plan agents)
- Implementing code (Edit, Write, Bash)

This skill adds two mandatory quality gates at the end:

```
[Normal Claude Code workflow] → Implementation complete
    ↓
Skill tool → skill: "feature:test-writing"  (테스트 작성)
    ↓
Skill tool → skill: "feature:code-review"   (코드 리뷰)
    ↓
Issues found? → Fix → Re-invoke "feature:code-review" (재검토 루프)
    ↓
Review cycle ends → 검증된 Codex 피드백을 루트 AGENTS.md + CLAUDE.md에 기록
    ↓
Done — ready for commit
```

## IMPORTANT: How to Invoke Sub-Skills

**You MUST use the Skill tool to invoke test-writing and code-review.** Do NOT call the test-writer or code-reviewer agents directly via the Agent tool — doing so bypasses the skill orchestration (project rule discovery, requirement verification, codex CLI 위임/fallback, re-review loop).

```
✅ CORRECT:  Skill(skill="feature:test-writing")
✅ CORRECT:  Skill(skill="feature:code-review")

❌ WRONG:    Agent(subagent_type="test-writer")
❌ WRONG:    Agent(subagent_type="code-reviewer")
❌ WRONG:    Agent(subagent_type="feature:test-writer")
```

The skills internally spawn the appropriate agents with full context (project rules, changed files, review focus areas). Calling agents directly skips all of this.

## What You Must Do

### During Plan Writing

When writing the plan .md file, **always include a verification section at the end**. This is critical because context compaction may lose the original skill instructions, but the plan file persists on disk and can be re-read.

Include this at the end of every plan file:

```markdown
## 검증

### 테스트 작성
- `Skill(skill="feature:test-writing")` 호출
- test-writer 서브 에이전트가 독립적으로 테스트 작성
- 테스트 실행 및 통과 확인

### 코드 리뷰
- `Skill(skill="feature:code-review")` 호출
- codex CLI 설치, 인증, Python 3.9+ 확인 시: codex exec review 3개(Bugs & Correctness / Simplicity & DRY / Project Conventions) 병렬 실행. 호출 실패 시 1회 재시도 후 사용자에게 보고(Claude 에이전트로 대체하지 않음)
- codex CLI 미설치 시: code-reviewer 서브 에이전트 3개 병렬로 코드 리뷰 (LEGACY)
- codex CLI 설치됐으나 인증 미완료 시: 사용자에게 알리고 인증/LEGACY 선택
- codex CLI와 인증은 준비됐지만 Python 3.9+가 없으면: durable ledger를 생략하지 말고 Python 설치/업그레이드 또는 LEGACY 선택을 기다림
- 리뷰 결과 사용자에게 보고
- 수정 발생 시 기존 working-tree 밖 review-cycle state의 `cycle_id`를 이어받아 `Skill(skill="feature:code-review")` 재호출 후 재검토
- 최종 리뷰 사이클이 끝나면 검증된 Codex 피드백을 루트 `AGENTS.md`와 `CLAUDE.md`에서 각각 정확히 한 번 참조할 수 있도록 기록
```

### After Implementation

Once code implementation is complete:

1. **Announce transition**: "구현이 완료되었습니다. 테스트 작성을 시작하겠습니다."
2. **Invoke test-writing skill**: `Skill(skill="feature:test-writing")`
3. **After tests pass, announce**: "테스트가 완료되었습니다. 코드 리뷰를 시작하겠습니다."
4. **Invoke code-review skill**: `Skill(skill="feature:code-review")`
5. **Report results to user**: Present review findings. Wait for a user decision only when requirement gaps or Critical/Warning findings remain; a Suggestion-only result can continue to persistence with explicit `제안됨` dispositions.
6. **If fixes are needed**: Fix the issues, then **re-invoke code-review skill** — `Skill(skill="feature:code-review")` again while resuming the exact `cycle_id` from its working-tree-external review state. Never start a fresh ledger for a re-review. Repeat until clean or user approves.
7. **Persist Codex feedback**: The code-review skill records verified, reusable Codex findings in the project-root `AGENTS.md` and `CLAUDE.md` only after the entire review/re-review cycle ends.

### Re-review is Mandatory

```
Fix issues → MUST re-invoke Skill(skill="feature:code-review")
           → Never skip this step
           → Repeat until no requirement gaps or Critical/Warning issues remain
```

If you fix issues found by the code review, re-invoke the code-review skill to verify the fixes.

## Why This Matters

Without explicit quality gates:
- Tests get "forgotten" under time pressure
- Reviews happen superficially or not at all
- Bugs ship to production that could have been caught

The test-writer agent operates as a **separate subprocess** with fresh context — it analyzes the code independently, without the biases that come from having written it. This produces more thorough test coverage than the implementing agent writing its own tests.

## Communication

All user-facing content in Korean. Announce phase transitions clearly so the user knows where they are in the workflow.
