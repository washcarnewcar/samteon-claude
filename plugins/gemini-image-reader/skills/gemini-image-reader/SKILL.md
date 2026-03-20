---
name: gemini-image-reader
description: |
  ALWAYS trigger when ANY image is present in the conversation — whether the user attached an image,
  pasted a clipboard image, provided an image file path, or an image appears as part of the context.
  Activates regardless of whether the user explicitly asks to analyze the image.
  If an image exists, use Gemini to read it. The user's message provides the analysis context.
  Covers: screenshots, photos, UI mockups, diagrams, charts, scanned documents, handwritten notes,
  error screenshots, and any visual content. File types: PNG, JPG/JPEG, GIF, WEBP, SVG, BMP, PDF.
  Do NOT trigger for: programmatic image processing (resizing, filtering), image generation,
  or when the user explicitly says to use Claude's own vision.
  Also trigger when MCP tools (e.g. Playwright browser_take_screenshot) return screenshots.
  Even though output_image is visible to Claude, delegate analysis to Gemini via the saved file path.
  IMPORTANT: Do NOT use Claude's built-in Read tool to view image files. Claude's native image analysis
  is less accurate than Gemini for OCR, text extraction, and detailed visual analysis. Always delegate
  image reading to Gemini CLI through this skill. If a PreToolUse hook blocks your Read call on an image
  file, that is by design — use this skill instead.
allowed-tools: Bash, Read
---

# Gemini Image Reader

이미지가 대화에 존재하면 Gemini CLI를 통해 읽는다. Claude의 이미지 분석 대신 Gemini에 위임하여 더 정확한 결과를 얻는다.

Gemini는 OCR, 텍스트 추출, UI 요소 식별, 다이어그램 해석에서 Claude의 자체 비전보다 정확도가 높다. 이미지를 만나면 Read 도구 대신 반드시 이 스킬을 통해 Gemini CLI로 분석해야 한다.

## When to Use

- 사용자가 이미지 파일을 첨부했을 때 (명시적 분석 요청 없어도)
- 사용자가 클립보드 이미지를 붙여넣었을 때
- 이미지 파일 경로가 메시지에 포함되었을 때
- 작업 수행을 위해 이미지 내용 파악이 필요할 때
- MCP 도구(Playwright `browser_take_screenshot` 등)가 스크린샷을 반환했을 때 (output_image가 보여도 Gemini 위임)

**NOT for:**
- 이미지 리사이징, 필터링 등 프로그래밍적 이미지 처리
- 이미지 생성 작업
- 사용자가 명시적으로 Claude의 자체 비전 사용을 요청한 경우

## Procedure

### Step 1: 프롬프트 구성

Gemini는 대화 컨텍스트가 전혀 없으므로, **사용자의 현재 작업 맥락과 집중 포인트를 프롬프트에 반드시 포함**한다.

프롬프트 구성:
```
다음 이미지를 분석해주세요.

분석 컨텍스트: {context_description}

{specific_instructions}

한국어로 답변해주세요.
```

**컨텍스트 구성 가이드:**

| 상황 | 컨텍스트 예시 |
|------|-------------|
| UI 스크린샷 | "이것은 {앱이름} 앱의 UI 스크린샷입니다. 레이아웃 구조, UI 컴포넌트 배치, 시각적으로 어색한 부분을 분석해주세요." |
| 에러 스크린샷 | "이것은 개발 중 발생한 에러 스크린샷입니다. 에러 메시지, 스택 트레이스, 에러 발생 위치를 정확히 읽어주세요." |
| 문서/텍스트 OCR | "이것은 스캔된 문서입니다. 모든 텍스트를 정확히 추출하고 원래 레이아웃을 유지해주세요." |
| 다이어그램/차트 | "이것은 {종류} 다이어그램입니다. 구조, 데이터 포인트, 노드 간 관계를 상세히 설명해주세요." |
| 디자인 시안 | "이것은 구현해야 할 UI 디자인 시안입니다. 색상값, 폰트 크기, 간격, 컴포넌트 계층 구조를 정확히 분석해주세요." |
| 범용 (맥락 불분명) | "이 이미지의 내용을 상세히 설명해주세요." |

**핵심 원칙:** 사용자의 메시지 내용 자체가 분석 컨텍스트다. 사용자가 "이 UI에서 버튼 위치 바꿔줘"라고 했다면, Gemini에게 "UI 레이아웃과 버튼 배치를 중점적으로 분석"하도록 컨텍스트를 구성한다.

### Step 2: Gemini CLI 호출 (wrapper 스크립트)

프롬프트를 구성한 뒤, wrapper 스크립트로 한 번에 실행한다. 스크립트가 이미지 경로 탐색, 절대 경로 변환, Gemini 호출을 모두 처리한다.

**파일 경로가 주어진 경우:**
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/gemini-analyze.sh "프롬프트 텍스트" "/path/to/image.png"
```

**클립보드/인라인 이미지 (파일 경로 없음):**
```bash
# 인자 없이 호출하면 image-cache에서 가장 최근 이미지를 자동 탐색
bash ${CLAUDE_PLUGIN_ROOT}/scripts/gemini-analyze.sh "프롬프트 텍스트"
```

**여러 이미지 동시 분석:**
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/gemini-analyze.sh "프롬프트 텍스트" "/path/1.png" "/path/2.png"
```

**Playwright 스크린샷:**
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/gemini-analyze.sh "프롬프트 텍스트" ".playwright-mcp/page-{timestamp}.png"
```

- Bash timeout: 120000ms 권장

### Step 3: 결과 활용

- Gemini의 분석 결과를 사용자에게 전달하고, 원래 작업에 활용한다
- **이미지를 다시 직접 분석하지 않는다** — Gemini 결과를 신뢰
- 사용자의 원래 요청(코드 작성, 버그 수정, UI 구현 등)에 Gemini 분석 결과를 바로 적용

## Error Handling

| 상황 | 대응 |
|------|------|
| Gemini CLI 미설치 | `which gemini` 확인 후 `npm install -g @google/gemini-cli` 안내 |
| 인증 실패 (AuthError) | 터미널에서 `gemini` 대화형으로 재인증 안내 |
| 파일 없음 | 경로 확인 후 사용자에게 정확한 경로 요청 |
| image-cache에 이미지 없음 | 사용자에게 이미지 파일 경로 직접 제공 요청 |
| 타임아웃 | 이미지 크기가 큰 경우 잘라서 재시도 안내 |

## Common Mistakes

| 실수 | 해결 |
|------|------|
| 컨텍스트 없이 "이 이미지 설명해줘"만 전달 | 사용자의 작업 맥락과 집중 포인트를 반드시 포함 |
| Claude가 이미지를 직접 분석하려고 함 | 이 스킬이 트리거되면 항상 Gemini에 위임. 직접 분석하지 않음 |
| osascript로 클립보드에서 이미지를 가져오려 함 | osascript는 사용하지 않는다. 스크립트가 image-cache를 자동 탐색 |
| Gemini 결과를 무시하고 자체 판단 | Gemini 분석을 신뢰하고 그 결과를 기반으로 작업 |
| Read 도구로 이미지를 직접 읽으려고 함 | PreToolUse hook이 차단함. 이 스킬을 통해 Gemini CLI 사용 |
| Playwright 스크린샷을 output_image로 직접 분석 | 파일 경로를 스크립트에 전달하여 Gemini에 위임 |
| wrapper 스크립트 없이 gemini CLI를 직접 호출 | 반드시 ${CLAUDE_PLUGIN_ROOT}/scripts/gemini-analyze.sh 사용 |
