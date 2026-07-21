# samton-plugins

Samton 구성원이 각자 만든 플러그인(Claude Code · Codex · ChatGPT Work)을 공유하고 함께 사용하는 팀 저장소입니다. 팀원 누구나 자신의 플러그인을 기여할 수 있고, 다른 팀원들은 한 곳에서 모두를 설치·업데이트할 수 있습니다. Claude Code 플러그인은 `.claude-plugin/marketplace.json`, Codex와 ChatGPT Work 플러그인은 루트 `.agents/plugins/marketplace.json`을 통해 각각 배포되며, 일부 플러그인의 스킬은 [skills.sh](https://skills.sh/) CLI로도 개별 설치가 가능합니다. Work 전용 플러그인의 본체는 [chatgpt-work/](./chatgpt-work) 아래에 둡니다.

## 수록 플러그인

| 이름 | 카테고리 | 설명 |
|---|---|---|
| **feature** | development | 기능 구현 워크플로우 (테스트 작성 + 코드 리뷰 품질 게이트 포함) |
| **claude-code-self-improving-skills** | development | 복잡한 작업 후 재사용 기법을 SKILL.md로 자동 증류·자기개선 (Hermes Agent 이식) |
| **claude-cowork-self-improving-skills** | development | Cowork(클라우드 컨테이너) 전용 자기개선 루프 — claude.ai '스킬 저장' 영속화, 콜드 컨테이너 race 회피 |
| **chatgpt-codex-self-improving-skills** | development | Codex hook + MCP 기반 자기개선 루프 (턴 리뷰, 스킬 telemetry, dry-run curator) |
| **chatgpt-work-self-improving-skills** | productivity | ChatGPT Work 대화에서 승인 기반으로 재사용 가능한 개선 지침·스킬 후보를 생성 |
| **recap** | development | 방금 끝낸 작업을 '이전 구조→문제→수정→영향받은 파일→검증' 5단 회고로 채팅에 정리 (파일 저장·커밋 없이 출력만) |
| **git** | git | Git 워크플로우 자동화: 세션 단위 커밋·푸시·PR·main 머지 |
| **ascii-diagram** | document | 한글 폭(2칸) 보정 ASCII 박스 다이어그램·ERD 텍스트 생성 (이미지 변환 없이 코드블록 전달) |
| **dev-log** | document | 빌드 에러·경고 해결 과정을 개발 블로그 스타일 마크다운으로 자동 기록 |
| **docx-report-generation** | document | python-docx 기반 한국어 Word 보고서 생성 (차트·다이어그램·PDF 변환) |
| **gemini-image-reader** | utility | 이미지를 Gemini CLI로 분석하여 텍스트 설명 반환 (스크린샷·문서·다이어그램) |
| **markdown-to-pdf** | document | 마크다운 문서를 네이비 테마 PDF로 변환 (한국어·이모지·테이블 지원) |
| **voice-transcriber** | utility | 음성 메시지 전사 + 화자 분리 (Discord/Telegram/파일, Qwen3-ASR MLX) |
| **tmap** | utility | SK TMap API 37개 엔드포인트 래퍼 (경로·POI·지오코딩·대중교통·실시간 교통 등) |

## 설치 방법

### 방법 1: Claude Code 플러그인 마켓플레이스 (권장)

Claude Code 내에서 마켓플레이스를 추가하면 모든 플러그인을 한 번에 관리할 수 있습니다:

```
/plugin marketplace add samton-inc/samton-plugins
```

그 후 원하는 플러그인을 개별 활성화:

```
/plugin install feature@samton-plugins
/plugin install tmap@samton-plugins
/plugin install voice-transcriber@samton-plugins
# ...필요한 것만
```

또는 `~/.claude/settings.json`의 `enabledPlugins`에 직접 추가:

```json
"enabledPlugins": {
  "feature@samton-plugins": true,
  "tmap@samton-plugins": true
}
```

자동 업데이트는 `extraKnownMarketplaces` 설정의 `autoUpdate: true`로 활성화됩니다.

### 방법 2: Codex · ChatGPT Work 공식 플러그인 marketplace

루트 marketplace를 추가하고 Codex 전용 자기개선 플러그인을 설치합니다:

```bash
codex plugin marketplace add samton-inc/samton-plugins
codex plugin add chatgpt-codex-self-improving-skills@samton-plugins
```

ChatGPT 데스크톱 앱의 Plugins Directory에는 현재 두 변형이 함께 표시됩니다. Codex에서는 `chatgpt-codex-self-improving-skills`, Work 모드에서는 `chatgpt-work-self-improving-skills`를 선택하세요. 현행 데스크톱 앱에서는 marketplace의 `policy.products`로 두 화면이 안정적으로 분리되지 않습니다.

기존 설치를 최신 marketplace 구조와 버전으로 갱신하려면 다음을 실행합니다:

```bash
codex plugin marketplace upgrade samton-plugins
codex plugin add chatgpt-codex-self-improving-skills@samton-plugins
```

갱신 후 ChatGPT 데스크톱 앱을 재시작하세요. `Samton Plugins` 아래에 두 변형이 함께 나타나며, 사용하는 모드에 맞는 플러그인을 설치하면 됩니다.

### 방법 3: skills.sh로 개별 스킬만 설치

Claude Code가 아닌 다른 에이전트 환경(Codex, Cursor, 독립 AI 워크플로우 등)에서 **스킬 단위**로만 설치하고 싶다면 [skills.sh](https://skills.sh/) CLI를 사용할 수 있습니다:

```bash
# 예: tmap 스킬만 설치
npx skills add https://github.com/samton-inc/samton-plugins/tree/main/plugins/tmap/skills/tmap

# 예: voice-transcriber 스킬만 설치
npx skills add https://github.com/samton-inc/samton-plugins/tree/main/plugins/voice-transcriber/skills/voice-transcriber

# 예: feature 스킬만 설치
npx skills add https://github.com/samton-inc/samton-plugins/tree/main/plugins/feature/skills/feature
```

각 플러그인의 스킬 경로는 `plugins/<plugin-name>/skills/<skill-name>/` 패턴을 따릅니다. 플러그인 내부 디렉토리 구조는 [여기](./plugins)에서 확인할 수 있습니다.

> **주의**: skills.sh 설치는 플러그인의 **스킬만** 가져오므로, 플러그인이 정의하는 hooks, agents, MCP 서버, commands 등은 포함되지 않습니다. 전체 기능이 필요하다면 Claude Code는 방법 1, Codex와 ChatGPT Work는 방법 2를 사용하세요.

## 외부 의존성

일부 플러그인은 외부 도구 또는 API 키가 필요합니다. 자세한 내용은 각 플러그인의 README/SKILL.md 참조:

| 플러그인 | 필요 의존성 |
|---|---|
| `feature` | Python 3.9+ (CODEX_MODE 리뷰 ledger), OpenAI Codex CLI (선택) |
| `claude-code-self-improving-skills` | Python 3 |
| `chatgpt-codex-self-improving-skills` | OpenAI Codex CLI |
| `tmap` | SK Open API AppKey (https://openapi.sk.com/) |
| `gemini-image-reader` | Google Gemini API 키 또는 CLI |
| `voice-transcriber` | ffmpeg, Qwen3-ASR MLX 모델 (MacOS 환경) |
| `docx-report-generation` | python-docx, matplotlib 등 Python 패키지 |
| `markdown-to-pdf` | Playwright, Chromium |

## 기여 / 문의

Samton 팀 공용 저장소입니다. Claude 플러그인은 `plugins/<name>/`에 본체를 두고 `.claude-plugin/marketplace.json`에 등록합니다. Codex 플러그인은 `plugins/<name>/.codex-plugin/plugin.json`, ChatGPT Work 플러그인은 `chatgpt-work/plugins/<name>/.codex-plugin/plugin.json`을 진입점으로 사용하며 둘 다 루트 `.agents/plugins/marketplace.json`에 등록합니다. 현행 데스크톱 앱에서는 두 변형이 같은 marketplace에 함께 표시되므로 각 모드에 맞는 변형을 선택합니다. 외부 사용자의 이슈·PR도 환영합니다.

- 이슈: https://github.com/samton-inc/samton-plugins/issues
- 저장소 관리자: 이정윤 <solstice@samton.co.kr>

## 라이선스

[MIT License](./LICENSE) — 2026 이정윤

## 참고

- [Claude Code 플러그인 공식 문서](https://docs.claude.com/en/docs/claude-code/plugins)
- [OpenAI Codex 플러그인 공식 문서](https://developers.openai.com/codex/plugins/build)
- [skills.sh — Vercel Labs](https://skills.sh/)
