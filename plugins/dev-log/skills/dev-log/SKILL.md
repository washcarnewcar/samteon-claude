---
name: dev-log
description: |
  Use when Claude has just fixed a build error, build warning, compiler error, linker error,
  type check error, runtime crash, deprecation warning, or any IDE/tool warning during development.
  Trigger AFTER the fix is confirmed working (build succeeds, warning resolved, tests pass).
  Do NOT trigger for: trivial typo fixes, user-requested code changes that aren't bug/warning fixes,
  or test-only changes. Covers all build systems: Xcode, Gradle, npm, cargo, go build, tsc, etc.
allowed-tools: Bash, Glob, Read, Write
---

# Dev Log Writer

빌드 에러/경고 해결 경험을 개발 블로그 스타일 마크다운으로 자동 기록한다.

## Overview

Claude가 개발 중 빌드 에러나 경고를 수정한 직후, 그 과정을 블로그 글처럼 기록한다. 개발자가 자기 디버깅 경험을 블로그에 남기는 것과 같은 톤으로 작성하며, 프로젝트의 `docs/dev-logs/` 디렉토리에 저장한다.

## When to Use

- 빌드 에러를 수정한 직후 (컴파일러, 링커, 타입 체크 등)
- 빌드 경고를 해결한 직후 (deprecation, unused, concurrency 등)
- 런타임 크래시의 원인을 찾아 수정한 직후
- IDE/도구 경고를 해결한 직후

**NOT for:**
- 사용자가 요청한 기능 구현이나 리팩토링 (에러/경고 수정이 아닌 것)
- 단순 오타 수정
- 테스트 코드만 변경한 경우

## Procedure

### 1. 복잡도 분류

방금 수정한 이슈를 분류한다:

| 분류 | 기준 | 분량 (코드 블록 제외) |
|------|------|----------------------|
| **Simple (TIL)** | 단일 경고, import 누락, deprecation, 타입 불일치 등 원인이 명확한 것 | 50~150단어 |
| **Detailed (Blog)** | 여러 파일 수정, 원인 추적 필요, workaround 필요, 아키텍처 이슈 | 300~500단어 |

### 2. 파일 생성

- **위치**: 현재 프로젝트의 `docs/dev-logs/` (없으면 `mkdir -p`로 생성)
- **파일명**: `YYYY-MM-DD-간결한-주제.md` (한글 slug 허용, 공백은 하이픈)
- **같은 날 같은 주제**: slug를 구분하여 별도 파일 생성
- **동일 빌드 사이클 연속 수정**: 하나의 포스트로 묶음. 별개 빌드 사이클이면 별도 포스트

### 3. 템플릿

**Simple (TIL)**:

```markdown
---
title: "{제목}"
date: YYYY-MM-DD
tags: [til, {플랫폼}, {카테고리}]
severity: warning | error
---

# {제목}

## 증상

{에러/경고 메시지 원문 코드블록}

## 원인

{1~2문장으로 간결하게}

## 해결

{수정 코드 diff 또는 핵심 변경 사항}
```

**Detailed (Blog)**:

```markdown
---
title: "{제목}"
date: YYYY-MM-DD
tags: [{플랫폼}, {프레임워크}, {카테고리}]
severity: warning | error
---

# {제목}

## 상황

{어떤 작업 중이었는지, 무엇이 발생했는지}

## 에러 내용

{에러/경고 메시지 원문 코드블록}

## 원인 분석

{왜 이 에러가 발생했는지 단계적 설명}

## 해결 과정

{시도한 접근과 최종 해결책, 코드 diff 포함}

## 배운 점

{핵심 교훈 1~2문장}
```

### 4. 작성 규칙

- **언어**: 한국어 (에러 메시지, 코드 블록은 원문 유지)
- **톤**: 개발자가 자기 블로그에 기록하는 자연스러운 톤. 딱딱한 보고서가 아닌 경험담.
- **tags 참조**:
  - 플랫폼: `swift`, `kotlin`, `typescript`, `rust`, `python`, `go`, `java` 등
  - 카테고리: `compiler`, `linker`, `deprecation`, `concurrency`, `ui`, `signing`, `dependency`, `config` 등
- **워크플로우 방해 최소화**: 파일 작성 후 한 줄로 안내만 출력
  - 예: "dev-log 작성 완료: `docs/dev-logs/2026-03-12-sendable-프로토콜-누락.md`"

## Common Mistakes

| 실수 | 해결 |
|------|------|
| 사용자 요청 기능 구현을 에러 수정으로 오인하고 트리거 | 사용자가 명시적으로 요청한 변경인지 확인. 에러/경고 메시지가 있었는지가 핵심 기준 |
| 에러 수정 전에 글을 작성하려고 함 | 반드시 수정이 확인된 후(빌드 성공, 경고 해소) 작성 |
| 글이 너무 길어서 작업 흐름을 방해 | Simple/Detailed 분류를 엄격히 적용. 대부분은 Simple |
| docs/dev-logs/ 경로를 프로젝트 외부에 생성 | 반드시 현재 작업 중인 프로젝트 루트의 docs/dev-logs/에 생성 |
