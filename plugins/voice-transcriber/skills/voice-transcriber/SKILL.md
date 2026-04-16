---
name: voice-transcriber
description: |
  이 스킬은 음성/오디오 파일이 포함된 메시지나 요청을 처리한다.
  다음 경우에 트리거된다:
  - Discord/Telegram 메시지의 첨부파일이 오디오 MIME 타입(audio/ogg, audio/mpeg, audio/wav, audio/mp4,
    audio/x-m4a, audio/aac, audio/flac, audio/opus)인 경우
  - Telegram의 attachment_kind가 "voice" 또는 "audio"인 경우
  - 사용자가 Claude Code 대화에서 오디오 파일 경로를 직접 제공한 경우
    (지원 확장자: .mp3, .m4a, .wav, .ogg, .oga, .opus, .flac, .aac, .wma, .mp4, .webm)
  두 가지 모드로 동작한다:
  - Mode A (음성 입력): 음성만 보낸 경우 — 전사 후 사용자의 말로 취급하여 자연스럽게 응답
  - Mode B (전사 서비스): 음성 + 텍스트 지시가 함께 온 경우 — 화자구분 전사 후 파일 저장 및 전달
  오디오가 아닌 첨부파일(이미지, 동영상, 문서)이나 텍스트 전용 메시지에서는 트리거하지 않는다.
allowed-tools: Bash, Read, Write
---

# Voice Transcriber

음성/오디오 파일을 Qwen3-ASR (1.7B, MLX)로 전사한다. Apple Silicon에서 로컬로 동작하며 외부 API가 불필요하다.

두 가지 모드를 지원한다:
- **Mode A** — 음성을 사용자의 말로 취급하여 자연스럽게 응답
- **Mode B** — 화자구분 전사 서비스로 동작하여 파일로 저장/전달

## When to Use

- Discord 메시지의 attachments에 오디오 MIME 타입이 포함된 경우
- Telegram 메시지에 `attachment_kind: "voice"` 또는 `"audio"`가 있는 경우
- 사용자가 Claude Code 대화에서 오디오 파일 경로를 직접 제공한 경우
- 지원 MIME: `audio/ogg`, `audio/mpeg`, `audio/wav`, `audio/mp4`, `audio/x-m4a`, `audio/aac`, `audio/flac`, `audio/opus`
- 지원 확장자: `.mp3`, `.m4a`, `.wav`, `.ogg`, `.oga`, `.opus`, `.flac`, `.aac`, `.wma`, `.mp4`, `.webm`

## When NOT to Use

- 텍스트로 된 일반 메시지
- 이미지, 동영상, 문서 등 오디오가 아닌 첨부파일
- 음악 파일 분석이나 오디오 편집 요청

## Procedure

### Step 0: 설정 확인

`.claude/voice-transcriber.local.md` 파일이 존재하는지 확인한다. (Bash로 `test -f .claude/voice-transcriber.local.md`)

**파일이 없으면** 사용자에게 모드 선택을 질문한다:

> 음성 전사 모드를 선택해주세요:
> - **server**: 모델을 메모리에 상주시켜 빠르게 전사합니다. 5분 유휴 시 모델을 자동 언로드하여 GPU 메모리를 해제합니다. (GPU 메모리 여유가 있는 경우 추천)
> - **cli**: 요청마다 모델을 새로 로드합니다. 느리지만 메모리를 사용할 때만 점유합니다.

선택에 따라 파일을 생성한다:

```bash
mkdir -p .claude
cat > .claude/voice-transcriber.local.md << 'LOCALEOF'
---
asr_mode: server
---
LOCALEOF
```

(`server` 또는 `cli`를 사용자 선택에 따라 기입)

**파일이 이미 있으면** 이 단계를 건너뛴다.

### Step 1: 소스 확인 및 파일 획득

메시지 소스에 따라 오디오 파일을 획득한다.

**Discord 메시지인 경우:**
```
mcp__plugin_discord_discord__download_attachment(chat_id=<chat_id>, message_id=<message_id>)
```

**Telegram 메시지인 경우:**
```
mcp__plugin_telegram_telegram__download_attachment(file_id=<attachment_file_id>)
```

**Claude Code에서 직접 파일 경로를 제공한 경우:**
다운로드 불필요. 제공된 경로를 그대로 사용한다. Bash로 파일 존재 여부만 확인한다.

### Step 2: 모드 판별

다음 기준으로 Mode A 또는 Mode B를 결정한다.

| 상황 | 모드 |
|------|------|
| Discord/Telegram 음성, 동반 텍스트 없음 | **A** |
| Discord/Telegram 음성 + 처리 지시 텍스트 | **B** |
| Claude Code에서 직접 파일 경로 제공 | **B** |
| "전사", "transcribe", "회의록", "파일로 저장" 등 키워드 포함 | **B** |

- 동반 텍스트가 파일명이나 플랫폼 자동 캡션("Voice message" 등) 수준이면 텍스트 없음으로 간주 → Mode A
- 판단이 어려운 경우 Mode A로 처리 (기존 동작 우선)

### Step 3A: Mode A — 음성 입력

전사 스크립트를 실행한다.

**IMPORTANT: Bash timeout을 반드시 120000ms로 설정할 것.**

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/transcribe.sh "<오디오_파일_경로>"
```

전사된 텍스트를 사용자의 실제 메시지로 취급하고, 그 내용을 바탕으로 응답한다.

- 전사 텍스트를 별도로 인용하거나 표시하지 않는다
- 원래 텍스트 메시지를 받은 것처럼 자연스럽게 응답한다
- 대화 맥락(채널, 이전 대화 흐름)을 유지한다

### Step 2B: 전사 옵션 확인 (Mode B 전용)

Mode B로 판별된 후, 전사를 실행하기 전에 사용자에게 질문한다:

1. **화자 구분 여부**: "화자 구분이 필요하신가요?"
   - 사용자가 이미 텍스트에서 화자구분을 언급했거나 ("회의록", "대화 전사" 등) 명시적으로 요청한 경우 → 질문 생략, 화자구분 사용
   - 단순 전사 요청인 경우 ("이거 텍스트로 변환해줘") → 질문
2. **화자 수**: 화자구분을 사용하는 경우, "몇 명이 대화에 참여했나요? (모르시면 자동 감지합니다)"

3. **전사 언어**: 기본값은 한국어. 사용자가 다른 언어를 요청하면 해당 언어로 변경.
   - 지원 언어: Korean, English, Chinese, Japanese, French, German, Spanish, Arabic, Hindi, Italian, Dutch, Portuguese, Russian, Turkish
   - 사용자가 명시하지 않으면 질문하지 않고 한국어로 진행

사용자 답변에 따른 분기:
- 화자구분 불필요 → Step 3B-simple로 진행 (diarize 없이 일반 전사)
- 화자구분 필요 + 인원 수 지정 → Step 3B로 진행 (`--num-speakers N` 포함)
- 화자구분 필요 + 인원 모름 → Step 3B로 진행 (자동 감지)
- 다른 언어 요청 시 → 모든 모드에서 `--language <LANG>` 추가

### Step 3B-simple: 단순 전사 (화자구분 없음)

화자구분 없이 일반 전사만 실행한다.

**IMPORTANT: Bash timeout을 반드시 120000ms로 설정할 것.**

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/transcribe.sh "<오디오_파일_경로>"
```

stdout으로 출력된 텍스트를 파일로 저장한다. Step 3B-2 (파일 저장) 및 Step 3B-3 (응답)으로 진행.

### Step 3B: 화자구분 전사

화자구분 전사 스크립트를 실행한다.

**IMPORTANT: Bash timeout을 반드시 300000ms로 설정할 것.** 화자 분리 모델 로딩에 추가 시간이 소요된다.

사용자가 화자 수를 지정한 경우:
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/transcribe.sh --diarize --num-speakers <N> "<오디오_파일_경로>"
```

화자 수를 모르는 경우 (자동 감지):
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/transcribe.sh --diarize "<오디오_파일_경로>"
```

사용자가 저장 경로를 지정한 경우 `--output "<저장_디렉토리>"` 추가.

스크립트가 자동으로 JSON → txt 변환까지 처리하며, stdout으로 생성된 txt 파일 경로를 출력한다.
stderr에 감지된 화자 수가 표시된다 (예: `감지된 화자: 3명`).

txt 포맷 예시:
```
참석자 1: 안녕하세요, 오늘 회의를 시작하겠습니다.
참석자 2: 네, 준비되었습니다.
참석자 1: 첫 번째 안건은 프로젝트 진행 상황입니다.
```

#### Step 3B-2: 파일 저장/이동

스크립트가 생성한 txt 파일이 사용자가 원하는 경로에 있으면 그대로 사용한다.
다른 경로로 이동이 필요한 경우 Bash로 `mv` 또는 `cp`를 실행한다.

#### Step 3B-3: 응답

**Discord/Telegram 소스인 경우:**
전사문 파일을 `reply` 도구의 `files` 파라미터로 첨부하여 응답한다.
```
reply(chat_id=<chat_id>, body="전사가 완료되었습니다.", files=["/tmp/recording.txt"])
```

**Claude Code 직접 파일인 경우:**
저장 경로를 텍스트로 안내한다.

## Error Handling

| 상황 | 대응 |
|------|------|
| mlx-qwen3-asr 미설치 | 설치 안내 메시지 출력 (venv 생성 + pip install) |
| diarize extras 미설치 | `~/.venvs/voice-transcriber/bin/python -m pip install "mlx-qwen3-asr[diarize]"` 실행 안내 |
| HF_TOKEN 미설정 | Hugging Face 토큰 설정 안내 (`export HF_TOKEN=hf_...`) |
| 오디오 파일 다운로드 실패 | 사용자에게 재전송 요청 |
| 직접 첨부 파일 미존재 | 파일 경로 재확인 요청 |
| 전사 결과가 빈 문자열 | 음성이 인식되지 않았음을 알리고 텍스트로 다시 보내달라고 요청 |
| 전사 스크립트 타임아웃 | 오디오가 너무 긴 경우 — 짧게 나눠서 보내달라고 요청 |

## Common Mistakes

| 실수 | 해결 |
|------|------|
| Mode A에서 전사 텍스트를 인용 형태로 표시 | 인용 없이 자연스럽게 응답 |
| 이미지 첨부파일에 대해 트리거 | 오디오 MIME 타입/확장자만 처리 |
| Bash timeout 기본값 사용 | Mode A: 120000ms, Mode B: 300000ms 설정 |
| 전사 전에 음성 내용을 추측하여 응답 | 반드시 전사 완료 후 응답 |
| Mode B에서 --diarize 없이 실행 | 화자구분이 필요한 경우 반드시 --diarize 플래그 사용 |
| Discord/Telegram Mode B에서 텍스트로만 응답 | 전사문 파일을 reply의 files로 첨부 |
