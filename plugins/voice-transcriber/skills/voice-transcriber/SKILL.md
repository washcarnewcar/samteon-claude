---
name: voice-transcriber
description: |
  이 스킬은 Discord 또는 Telegram 메시지에 음성/오디오 첨부파일이 포함되어 있을 때 사용한다.
  메시지 메타데이터에서 audio/ogg, audio/mpeg, audio/wav, audio/mp4 등 오디오 MIME 타입이 감지되거나,
  Telegram의 attachment_kind가 "voice" 또는 "audio"인 경우에 트리거된다.
  음성 메시지를 로컬 ASR 모델로 전사한 뒤, 전사된 텍스트를 기반으로 자연스럽게 응답한다.
  오디오가 아닌 첨부파일(이미지, 동영상, 문서)이나 텍스트 전용 메시지에서는 트리거하지 않는다.
allowed-tools: Bash, Read
---

# Voice Transcriber

Discord/Telegram 음성 메시지를 Qwen3-ASR (1.7B, MLX)로 전사하여 텍스트 입력으로 변환한다. Apple Silicon에서 로컬로 동작하며 외부 API가 불필요하다.

## When to Use

- Discord 메시지의 attachments에 `audio/ogg`, `audio/mpeg` 등 오디오 타입이 포함된 경우
- Telegram 메시지에 `attachment_kind: "voice"` 또는 `attachment_kind: "audio"`가 있는 경우
- 사용자가 음성으로 메시지를 보낸 것이 명확한 경우

## When NOT to Use

- 텍스트로 된 일반 메시지
- 이미지, 동영상, 문서 등 오디오가 아닌 첨부파일
- 음악 파일 분석이나 오디오 편집 요청

## Procedure

### Step 1: 음성 파일 다운로드

메시지 소스에 따라 적절한 다운로드 도구를 호출한다.

**Discord 메시지인 경우:**
MCP 도구 `mcp__plugin_discord_discord__download_attachment`를 호출한다.
```
download_attachment(chat_id=<chat_id>, message_id=<message_id>)
```

**Telegram 메시지인 경우:**
MCP 도구 `mcp__plugin_telegram_telegram__download_attachment`를 호출한다.
```
download_attachment(file_id=<attachment_file_id>)
```

다운로드 결과에서 로컬 파일 경로를 확인한다. 파일 확장자는 `.ogg`, `.oga`, `.mp3`, `.wav` 등이 될 수 있다.

### Step 2: 전사 실행

다운로드된 오디오 파일 경로를 transcribe.sh 스크립트에 전달한다.

**IMPORTANT: Bash timeout을 반드시 120000ms로 설정할 것.** 모델 최초 로딩에 수십 초가 소요될 수 있다.

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/transcribe.sh "<다운로드된_파일_경로>"
```

- 스크립트가 stdout으로 전사된 텍스트를 반환
- Qwen3-ASR-1.7B (bfloat16) 모델 사용 — 가장 높은 정확도
- ffmpeg이 오디오 포맷 변환을 자동 처리

### Step 3: 전사 결과로 응답

전사된 텍스트를 사용자의 실제 메시지로 취급하고, 그 내용을 바탕으로 응답한다.

- 전사 텍스트를 별도로 인용하거나 표시하지 않는다
- 원래 텍스트 메시지를 받은 것처럼 자연스럽게 응답한다
- 대화 맥락(채널, 이전 대화 흐름)을 유지한다

## Error Handling

| 상황 | 대응 |
|------|------|
| mlx-qwen3-asr 미설치 | 설치 안내 메시지 출력 (venv 생성 + pip install) |
| 오디오 파일 다운로드 실패 | 사용자에게 재전송 요청 |
| 전사 결과가 빈 문자열 | 음성이 인식되지 않았음을 알리고 텍스트로 다시 보내달라고 요청 |
| 전사 스크립트 타임아웃 | 오디오가 너무 긴 경우 — 짧게 나눠서 보내달라고 요청 |

## Common Mistakes

| 실수 | 해결 |
|------|------|
| 전사 텍스트를 인용 형태로 표시 | 인용 없이 자연스럽게 응답 |
| 이미지 첨부파일에 대해 트리거 | 오디오 MIME 타입만 처리 — image/* 무시 |
| Bash timeout 기본값(120s) 사용 안 함 | 모델 로딩 시간 고려하여 timeout 120000 설정 |
| 전사 전에 음성 내용을 추측하여 응답 | 반드시 전사 완료 후 응답 |
