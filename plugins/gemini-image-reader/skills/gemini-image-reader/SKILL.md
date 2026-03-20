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

### Step 1: 이미지 소스 확인

이미지 소스에 따라 파일 경로를 확보한다:

**파일 경로가 주어진 경우:**
```bash
# 반드시 이 명령으로 절대 경로 변환 (상대 경로를 @참조에 넣으면 Gemini가 파일을 못 찾음)
IMAGE_PATH=$(cd "$(dirname "{given_path}")" && pwd)/$(basename "{given_path}")
test -f "$IMAGE_PATH" && echo "OK: $IMAGE_PATH" || echo "NOT FOUND"
```
→ 출력된 `$IMAGE_PATH` 값을 이후 Step의 `@` 참조에 사용한다.

**클립보드/인라인 이미지인 경우 (파일 경로 없음):**

Claude Code는 inline 이미지를 `~/.claude/image-cache/{session-uuid}/{N}.png`에 캐시한다.
osascript 클립보드 방식은 사용하지 않는다.

```bash
# 가장 최근 이미지 찾기 (전체 image-cache에서)
IMAGE_PATH=$(find ~/.claude/image-cache -name "*.png" -type f -exec stat -f '%m %N' {} \; 2>/dev/null | sort -rn | head -1 | awk '{print $2}')
test -n "$IMAGE_PATH" && echo "OK: $IMAGE_PATH" || echo "NOT FOUND"
```

**못 찾은 경우:** 사용자에게 이미지 파일 경로를 직접 요청한다.

**MCP 도구 출력 이미지 (Playwright 스크린샷 등):**

Playwright `browser_take_screenshot`은 `.playwright-mcp/page-{timestamp}.png`에 파일을 저장하고, 동시에 output_image로 Claude에게 inline 이미지를 보여준다. **output_image가 보이더라도 직접 분석하지 말고**, 파일 경로를 절대 경로로 변환하여 Gemini에 위임한다:
```bash
# Playwright 결과에서 파일 경로를 추출하여 절대 경로로 변환
IMAGE_PATH=$(cd "$(dirname ".playwright-mcp/page-{timestamp}.png")" && pwd)/$(basename ".playwright-mcp/page-{timestamp}.png")
test -f "$IMAGE_PATH" && echo "OK: $IMAGE_PATH" || echo "NOT FOUND"
```

### Step 2: 분석 컨텍스트 구성

Gemini는 대화 컨텍스트가 전혀 없으므로, **사용자의 현재 작업 맥락과 집중 포인트를 프롬프트에 반드시 포함**한다.

프롬프트 구성 (이미지 파일은 `@` 접두사로 프롬프트 안에 참조):
```
다음 이미지를 분석해주세요.

분석 컨텍스트: {context_description}

{specific_instructions}

한국어로 답변해주세요. @{image_absolute_path}
```

**여러 이미지를 동시에 분석할 때:**
```
다음 이미지들을 분석해주세요.

분석 컨텍스트: {context_description}

{specific_instructions}

한국어로 답변해주세요. @{image1_path} @{image2_path} @{image3_path}
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

### Step 3: Gemini CLI 호출

**중요: 이미지 파일은 반드시 프롬프트 문자열 안에서 `@파일경로`로 참조한다. 별도 positional argument로 전달하면 안 된다.**

```bash
/opt/homebrew/bin/gemini -p "{constructed_prompt_with_@image_reference}" --yolo --include-directories "$HOME/.claude/image-cache" --include-directories /tmp 2>/dev/null
```

**올바른 예시:**
```bash
/opt/homebrew/bin/gemini -p "이 UI 스크린샷의 레이아웃을 분석해주세요. 한국어로 답변해주세요. @/path/to/image.png" --yolo --include-directories "$HOME/.claude/image-cache" --include-directories /tmp 2>/dev/null
```

**잘못된 예시 (에러 발생):**
```bash
# -p 플래그와 positional argument를 동시에 사용하면 에러!
/opt/homebrew/bin/gemini -p "이 이미지를 분석해주세요." /path/to/image.png --yolo 2>/dev/null
# => "Cannot use both a positional prompt and the --prompt (-p) flag together"
```

- `--yolo`: Gemini의 `read_file` 도구 호출을 자동 승인 (비대화형 실행)
- `2>/dev/null`: punycode deprecation 경고 등 stderr 노이즈 억제
- Bash timeout: 120000ms 권장

### Step 4: 결과 활용

- Gemini의 분석 결과를 사용자에게 전달하고, 원래 작업에 활용한다
- **이미지를 다시 직접 분석하지 않는다** — Gemini 결과를 신뢰
- 사용자의 원래 요청(코드 작성, 버그 수정, UI 구현 등)에 Gemini 분석 결과를 바로 적용

## Error Handling

| 상황 | 대응 |
|------|------|
| Gemini CLI 미설치 | `which gemini` 확인 후 `npm install -g @google/gemini-cli` 안내 |
| 인증 실패 (AuthError) | 터미널에서 `gemini` 대화형으로 재인증 안내 |
| 파일 없음 | 경로 확인 후 사용자에게 정확한 경로 요청 |
| image-cache/tmp 에 이미지 없음 | 사용자에게 이미지 파일 경로 직접 제공 요청 |
| 타임아웃 | 이미지 크기가 큰 경우 잘라서 재시도 안내 |
| `-p`와 positional arg 동시 사용 에러 | 이미지를 `@파일경로`로 프롬프트 안에 포함 |

## Common Mistakes

| 실수 | 해결 |
|------|------|
| 컨텍스트 없이 "이 이미지 설명해줘"만 전달 | 사용자의 작업 맥락과 집중 포인트를 반드시 포함 |
| Claude가 이미지를 직접 분석하려고 함 | 이 스킬이 트리거되면 항상 Gemini에 위임. 직접 분석하지 않음 |
| 상대 경로를 Gemini에 전달 | 반드시 절대 경로 사용 |
| 클립보드 이미지인데 osascript를 사용하려 함 | osascript는 사용하지 않는다. /tmp/gemini_images/에서 찾거나 사용자에게 경로 요청 |
| Gemini 결과를 무시하고 자체 판단 | Gemini 분석을 신뢰하고 그 결과를 기반으로 작업 |
| 이미지 파일을 positional argument로 전달 | `-p` 사용 시 `@파일경로`로 프롬프트 문자열 안에 포함 |
| Read 도구로 이미지를 직접 읽으려고 함 | PreToolUse hook이 차단함. 이 스킬을 통해 Gemini CLI 사용 |
| Playwright 스크린샷을 output_image로 직접 분석 | 파일 경로(`.playwright-mcp/...`)를 절대 경로로 변환하여 Gemini에 위임 |
| 상대 경로를 `@` 참조에 사용 | 반드시 Step 1의 Bash 명령으로 절대 경로 변환 후 `@` 참조에 사용 |
