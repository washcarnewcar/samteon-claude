# samteon-claude

이정윤이 운영하는 개인 Claude Code 플러그인 마켓플레이스입니다. 여러 개의 플러그인을 묶어서 한 저장소에서 관리하고, 각 플러그인은 Claude Code 마켓플레이스 시스템을 통해 설치·업데이트됩니다. 일부 플러그인의 스킬은 [skills.sh](https://skills.sh/) CLI로도 개별 설치가 가능합니다.

## 수록 플러그인

| 이름 | 카테고리 | 설명 |
|---|---|---|
| **feature** | development | 기능 구현 워크플로우 (테스트 작성 + 코드 리뷰 품질 게이트 포함) |
| **commit** | git | Git 커밋 자동화 및 푸시, PR 생성 |
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
/plugin marketplace add washcarnewcar/samteon-claude
```

그 후 원하는 플러그인을 개별 활성화:

```
/plugin install feature@samteon-claude
/plugin install tmap@samteon-claude
/plugin install voice-transcriber@samteon-claude
# ...필요한 것만
```

또는 `~/.claude/settings.json`의 `enabledPlugins`에 직접 추가:

```json
"enabledPlugins": {
  "feature@samteon-claude": true,
  "tmap@samteon-claude": true
}
```

자동 업데이트는 `extraKnownMarketplaces` 설정의 `autoUpdate: true`로 활성화됩니다.

### 방법 2: skills.sh로 개별 스킬만 설치

Claude Code가 아닌 다른 에이전트 환경(Codex, Cursor, 독립 AI 워크플로우 등)에서 **스킬 단위**로만 설치하고 싶다면 [skills.sh](https://skills.sh/) CLI를 사용할 수 있습니다:

```bash
# 예: tmap 스킬만 설치
npx skills add https://github.com/washcarnewcar/samteon-claude/tree/main/plugins/tmap/skills/tmap

# 예: voice-transcriber 스킬만 설치
npx skills add https://github.com/washcarnewcar/samteon-claude/tree/main/plugins/voice-transcriber/skills/voice-transcriber

# 예: feature 스킬만 설치
npx skills add https://github.com/washcarnewcar/samteon-claude/tree/main/plugins/feature/skills/feature
```

각 플러그인의 스킬 경로는 `plugins/<plugin-name>/skills/<skill-name>/` 패턴을 따릅니다. 플러그인 내부 디렉토리 구조는 [여기](./plugins)에서 확인할 수 있습니다.

> **주의**: skills.sh 설치는 플러그인의 **스킬만** 가져오므로, 플러그인이 정의하는 hooks, agents, MCP 서버, commands 등은 포함되지 않습니다. 전체 기능이 필요하다면 방법 1을 사용하세요.

## 외부 의존성

일부 플러그인은 외부 도구 또는 API 키가 필요합니다. 자세한 내용은 각 플러그인의 README/SKILL.md 참조:

| 플러그인 | 필요 의존성 |
|---|---|
| `tmap` | SK Open API AppKey (https://openapi.sk.com/) |
| `gemini-image-reader` | Google Gemini API 키 또는 CLI |
| `voice-transcriber` | ffmpeg, Qwen3-ASR MLX 모델 (MacOS 환경) |
| `docx-report-generation` | python-docx, matplotlib 등 Python 패키지 |
| `markdown-to-pdf` | Playwright, Chromium |

## 기여 / 문의

개인 프로젝트이지만 이슈·PR은 환영합니다.

- 이슈: https://github.com/washcarnewcar/samteon-claude/issues
- 이메일: solstice@samton.co.kr

## 라이선스

[MIT License](./LICENSE) — 2026 이정윤

## 참고

- [Claude Code 플러그인 공식 문서](https://docs.claude.com/en/docs/claude-code/plugins)
- [skills.sh — Vercel Labs](https://skills.sh/)
