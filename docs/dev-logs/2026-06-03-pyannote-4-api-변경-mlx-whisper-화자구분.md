---
title: "pyannote.audio 4.x API 변경에 부딪힌 mlx-whisper 화자구분 통합"
date: 2026-06-03
tags: [python, pyannote, mlx-whisper, asr, dependency]
severity: error
---

# pyannote.audio 4.x API 변경에 부딪힌 mlx-whisper 화자구분 통합

## 상황

voice-transcriber 플러그인에 기존 Qwen3-ASR 외에 가벼운 whisper 엔진을 추가하는 작업을 했다. 전사는 `mlx-whisper`(Apple Silicon GPU 가속)로 하고, whisper 자체에는 화자구분이 없으니 화자구분은 `pyannote.audio`로 따로 돌려서 whisper의 단어 단위 타임스탬프를 화자 턴에 매핑하는 구조다.

문제는 화자구분 코드를 흔히 알려진 pyannote 3.x 사용법(`use_auth_token`, 결과를 바로 `itertracks()`)대로 짰는데, 설치된 버전이 `pyannote.audio 4.0.4`라 두 군데서 연달아 깨졌다는 것.

## 에러 내용

먼저 파이프라인 로딩에서:

```
ERROR: Pipeline.from_pretrained() got an unexpected keyword argument 'use_auth_token'
```

인자 이름을 고친 뒤에는 결과 객체에서:

```
ERROR: 'DiarizeOutput' object has no attribute 'itertracks'
```

## 원인 분석

`pyannote.audio` 4.x에서 두 가지가 바뀌었다.

1. **`Pipeline.from_pretrained()`의 토큰 인자명이 `use_auth_token=` → `token=`으로 변경.** 시그니처를 직접 확인하니 `(checkpoint, revision=None, hparams_file=None, token: 'str | bool | None' = None, cache_dir=None)`이다.

2. **파이프라인 호출 결과가 `Annotation` 직접 반환에서 `DiarizeOutput` 데이터클래스로 변경.** 3.x에서는 결과에 바로 `.itertracks(yield_label=True)`를 호출했지만, 4.x의 `DiarizeOutput`은 두 개의 Annotation을 필드로 들고 있다.
   - `.speaker_diarization` — 겹치는 발화 구간 포함
   - `.exclusive_speaker_diarization` — 겹침 없음(전사 매핑용으로 권장)

   단어→화자 매핑은 겹침이 없는 쪽이 깔끔하므로 `exclusive_speaker_diarization`을 쓰는 게 맞다.

## 해결 과정

토큰 인자명을 `token=`으로 바꾸고, 결과에서 Annotation을 꺼내는 부분을 3.x/4.x 양쪽 호환되도록 `hasattr` 분기로 처리했다.

```python
# plugins/voice-transcriber/scripts/whisper_engine.py
from pyannote.audio import Pipeline
pipeline = Pipeline.from_pretrained(DIARIZE_PIPELINE, token=token)  # use_auth_token → token

...

output = pipeline(audio_path, **kwargs)
# pyannote 4.x는 DiarizeOutput(겹침 없는 exclusive 버전 포함)을,
# 3.x는 Annotation을 직접 반환한다.
if hasattr(output, "exclusive_speaker_diarization"):
    annotation = output.exclusive_speaker_diarization
elif hasattr(output, "speaker_diarization"):
    annotation = output.speaker_diarization
else:
    annotation = output
turns = [
    (segment.start, segment.end, speaker)
    for segment, _, speaker in annotation.itertracks(yield_label=True)
]
```

추가로, 토큰은 `HF_TOKEN` 환경변수가 없으면 `huggingface_hub.get_token()`으로 `huggingface-cli login` 저장 토큰을 폴백 사용하도록 했다(기존 설정을 깨지 않기 위해).

## 곁다리 발견: mlx-whisper의 모델 캐싱

서버 모드에서 유휴 시 모델 언로드를 구현하려고 mlx-whisper 0.4.3 내부를 보니, 모델 캐싱이 `lru_cache`가 아니라 클래스 싱글톤이었다.

```python
# mlx_whisper.transcribe.ModelHolder
class ModelHolder:
    model = None
    model_path = None
    @classmethod
    def get_model(cls, model_path, dtype):
        if cls.model is None or model_path != cls.model_path:
            cls.model = load_model(model_path, dtype=dtype)
            cls.model_path = model_path
        return cls.model
```

따라서 prewarm은 `ModelHolder.get_model(name, mx.float16)`, 언로드는 `ModelHolder.model = None; ModelHolder.model_path = None` 후 `gc.collect()` + `mx.clear_cache()`로 처리해야 한다. `transcribe()`의 기본 dtype이 fp16이라 prewarm도 `mx.float16`으로 맞춰야 캐시 키가 일치한다.

## 배운 점

라이브러리 메이저 버전이 올라가면 인자명뿐 아니라 **반환 타입 자체가 바뀔 수 있다.** 알려진 사용법이 안 먹으면 추측 말고 `inspect.signature`와 `inspect.getsource`로 실제 설치된 버전의 API를 직접 확인하는 게 가장 빠르다.
