#!/usr/bin/env python3
"""
mlx-qwen3-asr 상주 HTTP 서버
모델을 메모리에 올려두고 요청마다 재사용하여 전사 속도를 높인다.

Usage:
    python asr-server.py [--port 8787] [--model Qwen/Qwen3-ASR-1.7B]

API:
    POST /transcribe
    Body: {"audio_path": "/path/to/file.m4a", "language": "Korean"}
    Response: {"text": "전사된 텍스트", "duration_sec": 3.2}

    POST /transcribe
    Body: {"audio_path": "/path/to/file.m4a", "language": "Korean",
           "diarize": true, "num_speakers": 3}
    Response: {"text": "...", "speaker_segments": [...], "duration_sec": 12.5}

    GET /health
    Response: {"status": "ok", "model": "Qwen/Qwen3-ASR-1.7B"}
"""

import json
import time
import sys
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# mlx-qwen3-asr imports
import mlx.core as mx
import mlx_qwen3_asr as asr


class ASRSession:
    """모델을 한 번만 로드하고 재사용"""
    def __init__(self, model_name: str, dtype=mx.bfloat16):
        print(f"[ASR] 모델 로딩 중: {model_name} (dtype={dtype})")
        t0 = time.time()
        self.session = asr.Session(model=model_name, dtype=dtype)
        self.model_name = model_name
        elapsed = time.time() - t0
        print(f"[ASR] 모델 로딩 완료 ({elapsed:.1f}초)")

    def transcribe(self, audio_path: str, language: str = "Korean",
                   diarize: bool = False, num_speakers: int = None) -> dict:
        kwargs = dict(language=language, diarize=diarize)
        if diarize and num_speakers:
            kwargs["diarization_num_speakers"] = num_speakers

        result = self.session.transcribe(audio_path, **kwargs)

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


# 전역 세션 (서버 시작 시 초기화)
_asr_session: ASRSession = None


class ASRHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/transcribe":
            self._handle_transcribe()
        else:
            self._send_json(404, {"error": f"Not found: {self.path}"})

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "model": _asr_session.model_name if _asr_session else "not loaded"
            })
        else:
            self._send_json(404, {"error": f"Not found: {self.path}"})

    def _handle_transcribe(self):
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

            t0 = time.time()
            result = _asr_session.transcribe(
                audio_path, language=language,
                diarize=diarize, num_speakers=num_speakers
            )
            elapsed = time.time() - t0

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
        # 요청 로그를 stderr로 간결하게
        sys.stderr.write(f"[ASR] {args[0]} {args[1]} {args[2]}\n")


def main():
    global _asr_session

    parser = argparse.ArgumentParser(description="mlx-qwen3-asr HTTP server")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--model", default="Qwen/Qwen3-ASR-1.7B")
    args = parser.parse_args()

    _asr_session = ASRSession(args.model)

    server = HTTPServer(("127.0.0.1", args.port), ASRHandler)
    print(f"[ASR] 서버 시작: http://127.0.0.1:{args.port}")
    print(f"[ASR] POST /transcribe  |  GET /health")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ASR] 서버 종료")
        server.server_close()


if __name__ == "__main__":
    main()
