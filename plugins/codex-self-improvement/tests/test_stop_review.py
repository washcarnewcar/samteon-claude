import json
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))


def test_stop_review_detects_recent_user_transcript_signal(tmp_path):
    transcript = tmp_path / "thread.jsonl"
    transcript.write_text(
        json.dumps({"role": "user", "content": "다음부터 이 규칙은 항상 기억해 주세요."})
        + "\n",
        encoding="utf-8",
    )
    env = dict(os.environ, PLUGIN_DATA=str(tmp_path / "data"))
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "stop_review.py")],
        input=json.dumps({"turn_id": "t1", "transcript_path": str(transcript)}),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0

    signal_path = tmp_path / "data" / "review-signals.jsonl"
    row = json.loads(signal_path.read_text(encoding="utf-8").strip())
    assert row["signal"] is True
    assert row["signal_source"] == "transcript_user_messages"


def test_stop_review_loop_guard_writes_nothing(tmp_path):
    env = dict(os.environ, PLUGIN_DATA=str(tmp_path / "data"))
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "stop_review.py")],
        input=json.dumps({"stop_hook_active": True, "turn_id": "t1"}),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert not (tmp_path / "data" / "review-signals.jsonl").exists()
