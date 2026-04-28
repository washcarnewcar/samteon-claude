---
name: test-writing
description: |
  Write tests for new or modified code by discovering project conventions and using a dedicated test-writer agent.
  Use this skill when:
  - Code implementation is complete and needs test coverage
  - User asks "write tests", "add tests for X", "test this code"
  - User says "테스트 작성해줘" or "테스트 추가해줘"
  - The feature skill triggers the test-writing phase
  - Any code change that should be verified with automated tests
  Always use this skill rather than writing tests directly — the test-writer agent provides fresh perspective
  and catches edge cases that the implementing agent would miss.
allowed-tools: Task, Bash, Glob, Grep, Read, Edit, Write, TodoWrite
---

# Test Writing

You orchestrate test creation by discovering project conventions and delegating actual test writing to a dedicated **test-writer agent**. The agent runs as a separate subprocess with its own context, which means it analyzes the code independently — without the biases that come from having implemented it.

## Why a Separate Agent?

When the implementing agent writes its own tests, it tends to:
- Test only the "happy path" it had in mind during implementation
- Miss edge cases it didn't consider while coding
- Write assertions that match the implementation rather than the specification

A fresh agent reads the code for the first time and asks "what could go wrong?" — producing meaningfully different (and often better) test coverage.

## Process

### Phase 1: Discover Test Conventions

Before launching the agent, gather the information it needs:

1. **Read CLAUDE.md files** (root and subdirectories) to learn:
   - Test type policy (unit, integration, E2E, API-level)
   - Preferred test framework and assertion library
   - Forbidden test patterns (e.g., "no unit tests, integration only")
   - Required annotations or decorators
   - Test execution commands

2. **Find existing test files** to learn patterns:
   ```
   Glob: **/*Test*, **/*Spec*, **/*.test.*, **/*.spec.*
   ```
   Read 2-3 existing tests in the same domain to understand:
   - File and class structure
   - Naming conventions
   - Setup/teardown patterns
   - Data preparation approach
   - Assertion style

3. **Identify what changed**:
   - Run `git diff --name-only` to see modified files
   - Or use the file list from the implementation phase

### Phase 2: Launch test-writer Agent

Spawn the test-writer agent using the **Agent tool**:

```
Agent(
  subagent_type="feature:test-writer",
  description="테스트 작성",
  prompt="... (context from Phase 1)"
)
```

The agent prompt should include:
- Changed files list and what each change does
- Test conventions discovered from CLAUDE.md
- Existing test file patterns (structure, naming, framework)
- Test execution command
- Path to save test files
- Any special requirements from CLAUDE.md

The agent will independently:
1. Read the changed source files
2. Identify test targets (which functions/endpoints/components to test)
3. Design test cases (happy path, edge cases, error cases)
4. Write test files following discovered conventions
5. Run the tests
6. Fix any failures

### Phase 3: Verify and Report

After the agent completes:

1. **Check test results**: Did all tests pass?
2. **Review coverage**: Did the agent cover the main scenarios?
3. **Report to user**:

```
## 테스트 작성 완료

| 파일 | 테스트 수 | 상태 |
|------|---------|------|
| [TestFile] | [N]개 | ✅ 통과 |

### 작성된 테스트 케이스
1. **[test_name]**: [설명]
2. **[test_name]**: [설명]

### 실행 결과
✅ 전체 통과 (N/N)
```

4. If tests failed and the agent couldn't fix them, report failures with root cause analysis and ask the user how to proceed.

### Phase 4: Transition

After tests are complete and passing, announce:
"테스트가 완료되었습니다. 코드 리뷰를 시작하겠습니다."

Then invoke the code-review skill using the Skill tool:
```
Skill(skill="feature:code-review")
```

Do NOT call code-reviewer agents directly via the Agent tool — the skill handles orchestration, project rule discovery, and codex 플러그인 위임/fallback.

## Communication

All user-facing content in Korean. Agent prompts in English.
