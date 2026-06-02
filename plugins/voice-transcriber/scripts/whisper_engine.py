#!/usr/bin/env python3
"""mlx-whisper 전사 + pyannote 화자구분 엔진.

전사는 mlx-whisper(Apple Silicon GPU 가속)로, 화자구분은 pyannote로 처리한다.
whisper 자체에는 화자구분이 없으므로, whisper의 단어 단위 타임스탬프를
pyannote가 산출한 화자 턴에 매핑하여 단어 단위 speaker_segments를 만든다.

이 모듈은 CLI(transcribe-whisper.py)와 서버(asr-server.py) 양쪽에서 공유한다.
transcribe()의 반환 형태는 mlx-qwen3-asr 경로와 동일하게 맞춰
format-transcript.py가 그대로 재사용될 수 있도록 한다.
"""

import gc
import os

import mlx.core as mx

DEFAULT_WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
DIARIZE_PIPELINE = "pyannote/speaker-diarization-3.1"

# 전체 언어명 → ISO 코드 (mlx-whisper는 ISO 코드를 받는다)
_LANG_NAME_TO_CODE = {
    "korean": "ko",
    "english": "en",
    "chinese": "zh",
    "japanese": "ja",
    "french": "fr",
    "german": "de",
    "spanish": "es",
    "arabic": "ar",
    "hindi": "hi",
    "italian": "it",
    "dutch": "nl",
    "portuguese": "pt",
    "russian": "ru",
    "turkish": "tr",
}


def lang_to_code(language: str) -> str:
    """'Korean' 같은 전체 언어명 또는 'ko' 코드를 ISO 코드로 정규화한다."""
    if not language:
        return "ko"
    key = language.strip().lower()
    if key in _LANG_NAME_TO_CODE:
        return _LANG_NAME_TO_CODE[key]
    if len(key) == 2:  # 이미 코드로 보이는 경우 그대로 사용
        return key
    return "ko"


def _assign_speaker(start: float, end: float, turns: list) -> str:
    """단어의 [start, end] 구간을 화자 턴 중 가장 많이 겹치는 화자에 배정한다.

    겹치는 턴이 없으면 시간상 가장 가까운 턴의 화자로 폴백한다.
    """
    if not turns:
        return "SPEAKER_00"
    best_speaker = None
    best_overlap = 0.0
    for t_start, t_end, speaker in turns:
        overlap = min(end, t_end) - max(start, t_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker
    if best_speaker is not None:
        return best_speaker
    mid = (start + end) / 2.0
    return min(
        turns, key=lambda t: min(abs(mid - t[0]), abs(mid - t[1]))
    )[2]


class WhisperEngine:
    """mlx-whisper 모델 + (선택적) pyannote 파이프라인을 관리하는 세션."""

    def __init__(self, model_name: str = DEFAULT_WHISPER_MODEL):
        self.model_name = model_name
        self._diarizer = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self):
        """전사 모델을 미리 메모리에 적재한다(prewarm)."""
        if self._loaded:
            return
        from mlx_whisper.transcribe import ModelHolder
        # transcribe()의 기본 dtype(fp16)과 동일하게 적재해 캐시 키를 일치시킨다.
        ModelHolder.get_model(self.model_name, mx.float16)
        self._loaded = True

    def unload(self):
        """전사 모델과 화자구분 파이프라인을 모두 해제한다."""
        try:
            from mlx_whisper.transcribe import ModelHolder
            ModelHolder.model = None
            ModelHolder.model_path = None
        except Exception:
            pass
        self._diarizer = None
        self._loaded = False
        gc.collect()
        mx.clear_cache()

    def _get_diarizer(self):
        if self._diarizer is not None:
            return self._diarizer
        # 토큰: 환경변수 우선, 없으면 huggingface-cli login으로 저장된 토큰 사용
        token = (
            os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGINGFACE_TOKEN")
            or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        )
        if not token:
            try:
                from huggingface_hub import get_token
                token = get_token()
            except Exception:
                token = None
        from pyannote.audio import Pipeline
        pipeline = Pipeline.from_pretrained(DIARIZE_PIPELINE, token=token)
        if pipeline is None:
            raise RuntimeError(
                f"pyannote 파이프라인 로딩 실패: {DIARIZE_PIPELINE}. "
                "HF 토큰이 없거나 모델 사용 약관에 동의하지 않았습니다. "
                "`huggingface-cli login` 또는 `export HF_TOKEN=hf_...` 후 다시 시도하세요."
            )
        self._diarizer = pipeline
        return pipeline

    def transcribe(self, audio_path: str, language: str = "Korean",
                   diarize: bool = False, num_speakers: int = None) -> dict:
        """오디오를 전사한다.

        반환:
            {"text": str}                              # diarize=False
            {"text": str, "speaker_segments": [...]}   # diarize=True
        speaker_segments 각 항목: {"speaker", "start", "end", "text"} (단어 단위)
        """
        import mlx_whisper

        code = lang_to_code(language)
        # 환각(hallucination) 억제 옵션.
        # mlx-whisper 기본값(condition_on_previous_text=True)은 무음·노이즈 구간에서
        # 직전 텍스트를 반복 생성하는 환각을 길게 만든다("mem mem ...", 동일 토큰 반복).
        # 직전 텍스트 조건화를 끄고 무음/품질 임계값을 함께 적용해 반복 폭주를 막는다.
        decode_opts = {
            "path_or_hf_repo": self.model_name,
            "language": code,
            "word_timestamps": diarize,
            "verbose": None,
            "condition_on_previous_text": False,
            "compression_ratio_threshold": 2.4,
            "logprob_threshold": -1.0,
            "no_speech_threshold": 0.6,
            "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        }
        # hallucination_silence_threshold는 word_timestamps=True(=diarize)일 때만 동작한다.
        if diarize:
            decode_opts["hallucination_silence_threshold"] = 2.0
        result = mlx_whisper.transcribe(audio_path, **decode_opts)
        self._loaded = True

        text = (result.get("text") or "").strip()
        response = {"text": text}

        if diarize:
            words = []
            for seg in result.get("segments", []):
                for w in seg.get("words", []):
                    words.append({
                        "start": float(w.get("start", 0.0)),
                        "end": float(w.get("end", 0.0)),
                        "text": w.get("word", ""),
                    })
            response["speaker_segments"] = self._diarize_words(
                audio_path, words, num_speakers
            )

        return response

    def _diarize_words(self, audio_path: str, words: list,
                       num_speakers: int = None) -> list:
        pipeline = self._get_diarizer()
        kwargs = {}
        if num_speakers:
            kwargs["num_speakers"] = int(num_speakers)
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
        turns.sort()

        segments = []
        for w in words:
            start, end = w["start"], w["end"]
            speaker = _assign_speaker(start, end, turns)
            segments.append({
                "speaker": speaker,
                "start": start,
                "end": end,
                "text": w["text"],
            })
        return segments
