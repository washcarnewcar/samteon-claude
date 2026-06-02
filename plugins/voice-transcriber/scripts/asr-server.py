#!/usr/bin/env python3
"""
ASR 상주 HTTP 서버 (멀티 엔진 + idle timeout 지원)

모델을 메모리에 올려두고 요청마다 재사용하여 전사 속도를 높인다.
일정 시간 요청이 없으면 모델을 자동 언로드하여 GPU 메모리를 해제한다.

두 가지 엔진을 지원한다:
    qwen    — Qwen3-ASR (정확·무거움)
    whisper — whisper-large-v3-turbo + pyannote (빠름·균형)

한 번에 한 엔진만 메모리에 상주하며, 다른 엔진 요청이 오면
현재 모델을 언로드한 뒤 요청된 엔진을 로드한다.

Usage:
    python asr-server.py [--port 8787] [--default-engine whisper] [--idle-timeout 300]

API:
    POST /transcribe
    Body: {"audio_path": "/path/to/file.m4a", "language": "Korean", "engine": "whisper"}
    Response: {"text": "전사된 텍스트", "duration_sec": 3.2}

    POST /transcribe
    Body: {"audio_path": "...", "language": "Korean", "engine": "qwen",
           "diarize": true, "num_speakers": 3}
    Response: {"text": "...", "speaker_segments": [...], "duration_sec": 12.5}

    GET /health
    Response: {"status": "ok", "engine": "whisper", "model": "...",
               "model_loaded": true, "idle_remaining_sec": 120}
"""

import atexit
import gc
import json
import os
import signal
import sys
import time
import argparse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import mlx.core as mx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from whisper_engine import WhisperEngine, DEFAULT_WHISPER_MODEL  # noqa: E402

PID_FILE = "/tmp/asr-server.pid"

QWEN_MODEL = "Qwen/Qwen3-ASR-1.7B"
ENGINE_MODELS = {
    "qwen": QWEN_MODEL,
    "whisper": DEFAULT_WHISPER_MODEL,
}


class QwenSession:
    """mlx-qwen3-asr 모델 load/unload를 관리하는 세션"""

    engine = "qwen"

    def __init__(self, model_name: str = QWEN_MODEL, dtype=mx.bfloat16):
        self.model_name = model_name
        self.dtype = dtype
        self._session = None

    @property
    def is_loaded(self) -> bool:
        return self._session is not None

    def load(self):
        if self._session is not None:
            return
        import mlx_qwen3_asr as asr
        print(f"[ASR] qwen 모델 로딩 중: {self.model_name} (dtype={self.dtype})", flush=True)
        t0 = time.time()
        self._session = asr.Session(model=self.model_name, dtype=self.dtype)
        elapsed = time.time() - t0
        print(f"[ASR] qwen 모델 로딩 완료 ({elapsed:.1f}초)", flush=True)

    def unload(self):
        if self._session is None:
            return
        print("[ASR] qwen 모델 언로드 중...", flush=True)
        del self._session
        self._session = None
        gc.collect()
        mx.clear_cache()
        print("[ASR] qwen 모델 언로드 완료 (GPU 메모리 해제)", flush=True)

    def transcribe(self, audio_path: str, language: str = "Korean",
                   diarize: bool = False, num_speakers: int = None) -> dict:
        self.load()

        kwargs = dict(language=language, diarize=diarize)
        if diarize and num_speakers:
            kwargs["diarization_num_speakers"] = num_speakers

        result = self._session.transcribe(audio_path, **kwargs)

        # 텍스트 추출
        text = ""
        if hasattr(result, 'text') and result.text:
            text = result.text
        elif hasattr(result, 'segments') and result.segments:
            text = "".join(seg.text for seg in result.segments)
        elif hasattr(result, 'chunks') and result.chunks:
            text = "".join(chunk.text for chunk in result.chunks)
        else:
            text = str(result)

        response = {"text": text}

        # 화자구분 결과 포함
        if diarize and hasattr(result, 'speaker_segments') and result.speaker_segments:
            segments = []
            for seg in result.speaker_segments:
                if isinstance(seg, dict):
                    segments.append({
                        "speaker": seg.get("speaker", ""),
                        "start": seg.get("start", 0),
                        "end": seg.get("end", 0),
                        "text": seg.get("text", "")
                    })
                else:
                    segments.append({
                        "speaker": seg.speaker,
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text
                    })
            response["speaker_segments"] = segments

        return response


def _build_session(engine: str):
    """엔진 이름으로 세션 객체를 생성한다."""
    if engine == "whisper":
        return WhisperEngine(ENGINE_MODELS["whisper"])
    if engine == "qwen":
        return QwenSession(ENGINE_MODELS["qwen"])
    raise ValueError(f"알 수 없는 엔진: {engine}")


class SessionManager:
    """한 번에 하나의 엔진만 상주시키며, 엔진 전환 시 교체한다."""

    def __init__(self):
        self.engine = None
        self.session = None

    @property
    def is_loaded(self) -> bool:
        return self.session is not None and self.session.is_loaded

    @property
    def model_name(self) -> str:
        return self.session.model_name if self.session else "not loaded"

    def get(self, engine: str):
        """요청 엔진의 세션을 반환한다. 현재 상주 엔진과 다르면 교체한다."""
        if self.session is not None and self.engine == engine and self.session.is_loaded:
            return self.session
        if self.session is not None and self.engine != engine:
            print(f"[ASR] 엔진 전환: {self.engine} → {engine}", flush=True)
            self.session.unload()
            self.session = None
        if self.session is None:
            self.session = _build_session(engine)
            self.engine = engine
        self.session.load()
        return self.session

    def unload(self):
        if self.session is not None:
            self.session.unload()


# 전역 상태
_manager: SessionManager = None
_last_activity: float = 0.0
_idle_timeout: int = 300
_lock = threading.Lock()


class ASRHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/transcribe":
            self._handle_transcribe()
        else:
            self._send_json(404, {"error": f"Not found: {self.path}"})

    def do_GET(self):
        if self.path == "/health":
            elapsed = time.time() - _last_activity
            remaining = max(0, _idle_timeout - elapsed)
            self._send_json(200, {
                "status": "ok",
                "engine": _manager.engine if _manager else None,
                "model": _manager.model_name if _manager else "not loaded",
                "model_loaded": _manager.is_loaded if _manager else False,
                "idle_remaining_sec": round(remaining),
            })
        else:
            self._send_json(404, {"error": f"Not found: {self.path}"})

    def _handle_transcribe(self):
        global _last_activity
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            audio_path = data.get("audio_path", "")
            language = data.get("language", "Korean")
            engine = data.get("engine") or _manager.engine or "whisper"
            diarize = data.get("diarize", False)
            num_speakers = data.get("num_speakers", None)

            if not audio_path:
                self._send_json(400, {"error": "audio_path is required"})
                return

            if not Path(audio_path).exists():
                self._send_json(400, {"error": f"File not found: {audio_path}"})
                return

            if engine not in ENGINE_MODELS:
                self._send_json(400, {"error": f"Unknown engine: {engine}"})
                return

            # 엔진 로드/전환과 전사는 직렬화한다(모델 교체 경쟁 방지).
            with _lock:
                _last_activity = time.time()
                t0 = time.time()
                session = _manager.get(engine)
                result = session.transcribe(
                    audio_path, language=language,
                    diarize=diarize, num_speakers=num_speakers
                )
                elapsed = time.time() - t0
                _last_activity = time.time()

            result["duration_sec"] = round(elapsed, 2)
            self._send_json(200, result)

        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        sys.stderr.write(f"[ASR] {args[0]} {args[1]} {args[2]}\n")


def _idle_watchdog(manager: "SessionManager", timeout: int):
    """30초마다 체크, 유휴 시간 초과 시 상주 모델 언로드"""
    global _last_activity
    while True:
        time.sleep(30)
        with _lock:
            idle = time.time() - _last_activity
        if idle >= timeout and manager.is_loaded:
            print(f"[ASR] {timeout}초 유휴 — 모델 언로드", flush=True)
            manager.unload()


def _write_pid():
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def main():
    global _manager, _last_activity, _idle_timeout

    parser = argparse.ArgumentParser(description="ASR multi-engine HTTP server")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--default-engine", default="whisper",
                        choices=list(ENGINE_MODELS.keys()),
                        help="시작 시 미리 로드할 엔진 (기본 whisper)")
    parser.add_argument("--idle-timeout", type=int, default=300,
                        help="모델 언로드까지 유휴 시간 (초, 기본 300)")
    args = parser.parse_args()

    _idle_timeout = args.idle_timeout
    _last_activity = time.time()

    _write_pid()
    atexit.register(_remove_pid)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    _manager = SessionManager()
    # 기본 엔진을 미리 로드해 첫 요청 지연을 줄인다.
    _manager.get(args.default_engine)

    watchdog = threading.Thread(
        target=_idle_watchdog,
        args=(_manager, _idle_timeout),
        daemon=True,
    )
    watchdog.start()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), ASRHandler)
    print(f"[ASR] 서버 시작: http://127.0.0.1:{args.port}", flush=True)
    print(f"[ASR] POST /transcribe  |  GET /health", flush=True)
    print(f"[ASR] 유휴 타임아웃: {_idle_timeout}초", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ASR] 서버 종료")
        server.server_close()


if __name__ == "__main__":
    main()
