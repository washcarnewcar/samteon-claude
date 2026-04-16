#!/usr/bin/env python3
"""
mlx-qwen3-asr 상주 HTTP 서버 (idle timeout 지원)

모델을 메모리에 올려두고 요청마다 재사용하여 전사 속도를 높인다.
일정 시간 요청이 없으면 모델을 자동 언로드하여 GPU 메모리를 해제한다.

Usage:
    python asr-server.py [--port 8787] [--model Qwen/Qwen3-ASR-1.7B] [--idle-timeout 300]

API:
    POST /transcribe
    Body: {"audio_path": "/path/to/file.m4a", "language": "Korean"}
    Response: {"text": "전사된 텍스트", "duration_sec": 3.2}

    POST /transcribe
    Body: {"audio_path": "/path/to/file.m4a", "language": "Korean",
           "diarize": true, "num_speakers": 3}
    Response: {"text": "...", "speaker_segments": [...], "duration_sec": 12.5}

    GET /health
    Response: {"status": "ok", "model": "...", "model_loaded": true, "idle_remaining_sec": 120}
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

PID_FILE = "/tmp/asr-server.pid"


class ASRSession:
    """모델 load/unload를 관리하는 세션"""

    def __init__(self, model_name: str, dtype=mx.bfloat16):
        self.model_name = model_name
        self.dtype = dtype
        self._session = None
        self.load()

    @property
    def is_loaded(self) -> bool:
        return self._session is not None

    def load(self):
        if self._session is not None:
            return
        import mlx_qwen3_asr as asr
        print(f"[ASR] 모델 로딩 중: {self.model_name} (dtype={self.dtype})", flush=True)
        t0 = time.time()
        self._session = asr.Session(model=self.model_name, dtype=self.dtype)
        elapsed = time.time() - t0
        print(f"[ASR] 모델 로딩 완료 ({elapsed:.1f}초)", flush=True)

    def unload(self):
        if self._session is None:
            return
        print("[ASR] 모델 언로드 중...", flush=True)
        del self._session
        self._session = None
        gc.collect()
        mx.clear_cache()
        print("[ASR] 모델 언로드 완료 (GPU 메모리 해제)", flush=True)

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


# 전역 상태
_asr_session: ASRSession = None
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
                "model": _asr_session.model_name if _asr_session else "not loaded",
                "model_loaded": _asr_session.is_loaded if _asr_session else False,
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
            diarize = data.get("diarize", False)
            num_speakers = data.get("num_speakers", None)

            if not audio_path:
                self._send_json(400, {"error": "audio_path is required"})
                return

            if not Path(audio_path).exists():
                self._send_json(400, {"error": f"File not found: {audio_path}"})
                return

            with _lock:
                _last_activity = time.time()

            t0 = time.time()
            result = _asr_session.transcribe(
                audio_path, language=language,
                diarize=diarize, num_speakers=num_speakers
            )
            elapsed = time.time() - t0

            with _lock:
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


def _idle_watchdog(session: ASRSession, timeout: int):
    """30초마다 체크, 유휴 시간 초과 시 모델 언로드"""
    global _last_activity
    while True:
        time.sleep(30)
        with _lock:
            idle = time.time() - _last_activity
        if idle >= timeout and session.is_loaded:
            print(f"[ASR] {timeout}초 유휴 — 모델 언로드", flush=True)
            session.unload()


def _write_pid():
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def main():
    global _asr_session, _last_activity, _idle_timeout

    parser = argparse.ArgumentParser(description="mlx-qwen3-asr HTTP server")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--model", default="Qwen/Qwen3-ASR-1.7B")
    parser.add_argument("--idle-timeout", type=int, default=300,
                        help="모델 언로드까지 유휴 시간 (초, 기본 300)")
    args = parser.parse_args()

    _idle_timeout = args.idle_timeout
    _last_activity = time.time()

    _write_pid()
    atexit.register(_remove_pid)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    _asr_session = ASRSession(args.model)

    watchdog = threading.Thread(
        target=_idle_watchdog,
        args=(_asr_session, _idle_timeout),
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
