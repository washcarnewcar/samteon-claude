from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = PLUGIN_ROOT / "scripts" / "review_feedback.py"
SPEC = importlib.util.spec_from_file_location("feature_review_feedback", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
review_feedback = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review_feedback)


class FakeWindowsLocking:
    LK_LOCK = 1
    LK_UNLCK = 2

    def __init__(self, fail_mode: int | None = None):
        self.fail_mode = fail_mode
        self.calls: list[tuple[int, int, int, int]] = []

    def locking(self, descriptor: int, mode: int, length: int) -> None:
        position = os.lseek(descriptor, 0, os.SEEK_CUR)
        self.calls.append((descriptor, mode, length, position))
        if mode == self.fail_mode:
            raise OSError(f"injected Windows lock failure: {mode}")


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_state_dir(repo: Path) -> Path:
    return Path(run_git(repo, "rev-parse", "--absolute-git-dir")) / (
        review_feedback.STATE_DIR_NAME
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.name", "Feature Tests")
    run_git(repo, "config", "user.email", "feature-tests@example.com")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    run_git(repo, "add", "tracked.txt")
    run_git(repo, "commit", "-qm", "initial")
    return repo


def make_finding(
    finding_id: str = "finding-a",
    *,
    scope: str = "src/**",
    rule: str = "미래 구현에서는 입력 경계를 검증합니다.",
    disposition: str = "해결됨",
    reusable: bool = True,
    severity: str = "warning",
    coverage: dict | None = None,
) -> dict:
    return {
        "id": finding_id,
        "scope": scope,
        "rule": rule,
        "review_date": "2026-07-20",
        "disposition": disposition,
        "reusable": reusable,
        "severity": severity,
        "issue": "검증 누락",
        "evidence": "src/example.py:10",
        "source_rounds": [1],
        "coverage": coverage
        or {
            "AGENTS.md": {"kind": "managed"},
            "CLAUDE.md": {"kind": "managed"},
        },
    }


def start_slot(state: dict, slot: str, *, job_id: str) -> dict:
    reserved = review_feedback.reserve_launches(state, [slot])
    return review_feedback.mark_slot_running(
        reserved,
        slot,
        job_id=job_id,
        attempt=reserved["reviewer_slots"][slot]["attempt"],
    )


def complete_round(
    state: dict,
    snapshot: dict,
    state_dir: Path,
    *,
    gaps: list[dict] | None = None,
    findings: list[dict] | None = None,
) -> dict:
    updated = review_feedback.begin_round(state, snapshot)
    round_dir = state_dir / f"round-{updated['round']}"
    round_dir.mkdir(parents=True, exist_ok=True)
    for slot in review_feedback.REVIEWER_SLOTS:
        output_path = round_dir / f"{slot}.md"
        output_path.write_text(f"{slot} review output\n", encoding="utf-8")
        output_digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
        updated = start_slot(updated, slot, job_id=f"job-{slot}")
        updated = review_feedback.mark_slot_result(
            updated,
            slot,
            succeeded=True,
            output_path=f"round-{updated['round']}/{slot}.md",
            attempt=updated["reviewer_slots"][slot]["attempt"],
            output_digest=output_digest,
            state_dir=state_dir,
        )
    updated = review_feedback.mark_round_reviewed(
        updated, snapshot, cycle_dir=state_dir
    )
    updated = review_feedback.record_requirement_gaps(updated, gaps or [])
    updated = review_feedback.record_verified_findings(updated, findings or [])
    return review_feedback.consolidate_review_round(updated)


def write_ready_state(
    repo: Path,
    findings: list[dict],
    *,
    cycle_id: str = "cycle-1",
) -> Path:
    snapshot = review_feedback.capture_repo_snapshot(repo)
    state = review_feedback.initialize_state(
        repo,
        {"task": "persist feedback"},
        snapshot=snapshot,
        cycle_id=cycle_id,
    )
    state_dir = git_state_dir(repo)
    state_path = review_feedback.create_state_dir(state_dir, state)
    desired_findings = deepcopy(findings)
    recorded_findings = deepcopy(findings)
    blocking_decisions: dict[str, str] = {}
    for finding in recorded_findings:
        severity = str(finding.get("severity", "")).lower()
        disposition = str(finding.get("disposition", ""))
        if severity in review_feedback.BLOCKING_SEVERITIES and disposition in {
            "해결됨",
            "사용자 수용",
            "보류",
        }:
            blocking_decisions[str(finding["id"])] = disposition
            finding["disposition"] = "open"
    state = complete_round(
        state,
        snapshot,
        state_dir,
        findings=recorded_findings,
    )
    if any(disposition == "해결됨" for disposition in blocking_decisions.values()):
        state = review_feedback.prepare_rereview(state, snapshot)
        state = complete_round(state, snapshot, state_dir)
    if blocking_decisions:
        state = review_feedback.apply_user_decisions(state, blocking_decisions)
    assert [finding["id"] for finding in state["findings"]] == [
        finding["id"] for finding in desired_findings
    ]
    state = review_feedback.finalize_for_persistence(state, snapshot)
    review_feedback.atomic_write_json(state_path, state)
    return state_path


def crash_persist_at(
    state_path: Path, event: str, exit_code: int
) -> subprocess.CompletedProcess:
    script = """
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location("feature_review_feedback_crash", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

def crash_hook(event, _context):
    if event == sys.argv[3]:
        os._exit(int(sys.argv[4]))

module.persist_feedback(sys.argv[2], hook=crash_hook)
raise SystemExit("requested crash event was not observed")
"""
    return subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(HELPER_PATH),
            str(state_path),
            event,
            str(exit_code),
        ],
        capture_output=True,
        text=True,
    )


def run_persist_cli(state_path: Path) -> subprocess.CompletedProcess:
    cycle_id = review_feedback.read_state(state_path)["cycle_id"]
    return subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "persist",
            "--state",
            str(state_path),
            "--cycle-id",
            cycle_id,
        ],
        capture_output=True,
        text=True,
    )


def file_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_state_init_and_resume_require_exact_cycle_repo_and_scope(git_repo: Path):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    scope = {"task": "feature-a", "plan": ["one"]}
    state = review_feedback.initialize_state(
        git_repo, scope, snapshot=snapshot, cycle_id="cycle-a"
    )

    assert state["round"] == 0
    assert state["pending_action"] == "launch-round"
    assert (
        review_feedback.resume_action(
            state,
            cycle_id="cycle-a",
            repo_root=git_repo,
            scope_identity=scope,
        )
        == "launch-round"
    )

    with pytest.raises(review_feedback.StateError, match="cycle_id mismatch"):
        review_feedback.resume_action(
            state,
            cycle_id="different-cycle",
            repo_root=git_repo,
            scope_identity=scope,
        )
    with pytest.raises(review_feedback.StateError, match="repo_root mismatch"):
        review_feedback.resume_action(
            state,
            cycle_id="cycle-a",
            repo_root=git_repo.parent,
            scope_identity=scope,
        )
    with pytest.raises(
        review_feedback.StateError, match="task/scope identity mismatch"
    ):
        review_feedback.resume_action(
            state,
            cycle_id="cycle-a",
            repo_root=git_repo,
            scope_identity={"task": "feature-b"},
        )


def test_state_init_recovers_only_an_exact_empty_orphan_directory(git_repo: Path):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="orphaned-init"
    )
    state_dir = git_state_dir(git_repo)
    state_dir.mkdir(mode=0o755)
    interrupted_temp = state_dir.parent / f".{state_dir.name}.init-interrupted"
    interrupted_temp.mkdir(mode=0o700)
    (interrupted_temp / ".state.json.partial").write_text(
        "partial initial ledger\n", encoding="utf-8"
    )

    state_path = review_feedback.create_state_dir(state_dir, state)

    assert state_path == state_dir / review_feedback.STATE_FILE
    assert review_feedback.read_state(state_path) == state
    assert file_mode(state_dir) == 0o700
    assert interrupted_temp.is_dir()


@pytest.mark.parametrize("status", ("aborted", "complete"))
def test_terminal_state_is_not_automatically_resumed(git_repo: Path, status: str):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state["status"] = status

    with pytest.raises(
        review_feedback.StateError, match=f"cannot automatically resume {status}"
    ):
        review_feedback.resume_action(
            state,
            cycle_id="cycle-a",
            repo_root=git_repo,
            scope_identity="scope",
        )


def test_run_reviewers_dispatch_collects_existing_jobs(git_repo: Path):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state = review_feedback.begin_round(state, snapshot)

    assert (
        review_feedback.resume_action(
            state,
            cycle_id="cycle-a",
            repo_root=git_repo,
            scope_identity="scope",
        )
        == "run-reviewers"
    )


def test_launch_reservation_prevents_duplicate_restart_and_requires_generation(
    git_repo: Path,
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="launch-reservation"
    )
    state = review_feedback.begin_round(state, snapshot)

    with pytest.raises(review_feedback.StateError, match="not launch-reserved"):
        review_feedback.mark_slot_running(
            state, "bugs", job_id="unreserved-job", attempt=1
        )

    reserved = review_feedback.reserve_launches(
        state, list(review_feedback.REVIEWER_SLOTS)
    )
    summary = review_feedback._state_summary(reserved)
    assert summary["launch_slots"] == []
    assert summary["collect_slots"] == []
    assert summary["launching_slots"] == list(review_feedback.REVIEWER_SLOTS)
    assert (
        review_feedback.resume_action(
            reserved,
            cycle_id="launch-reservation",
            repo_root=git_repo,
            scope_identity="scope",
        )
        == "reconcile-launches"
    )
    with pytest.raises(review_feedback.StateError, match="may be active"):
        review_feedback.abort_state(reserved, "stop")

    attached = review_feedback.mark_slot_running(
        reserved, "bugs", job_id="job-bugs", attempt=1
    )
    assert (
        review_feedback.mark_slot_running(
            attached, "bugs", job_id="job-bugs", attempt=1
        )
        == attached
    )
    with pytest.raises(review_feedback.StateError, match="stale reviewer attempt"):
        review_feedback.mark_slot_running(
            attached, "bugs", job_id="job-bugs", attempt=2
        )
    with pytest.raises(review_feedback.StateError, match="another job"):
        review_feedback.mark_slot_running(
            attached, "bugs", job_id="different-job", attempt=1
        )
    with pytest.raises(review_feedback.StateError, match="stale reviewer attempt"):
        review_feedback.mark_slot_result(
            attached,
            "bugs",
            succeeded=False,
            output_path=None,
            attempt=2,
        )


def test_reserved_launch_can_attach_while_another_slot_awaits_decision(
    git_repo: Path,
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="multi-retry-reconcile"
    )
    state = review_feedback.begin_round(state, snapshot)
    for slot in ("bugs", "simplicity"):
        state = start_slot(state, slot, job_id=f"{slot}-attempt-1")
        state = review_feedback.mark_slot_result(
            state,
            slot,
            succeeded=False,
            output_path=None,
            attempt=1,
        )

    reserved = review_feedback.reserve_launches(state, ["bugs", "simplicity"])
    awaiting = review_feedback.mark_slot_result(
        reserved,
        "bugs",
        succeeded=False,
        output_path=None,
        attempt=2,
    )
    assert awaiting["pending_action"] == "await-reviewer-decision"
    assert (
        review_feedback.resume_action(
            awaiting,
            cycle_id="multi-retry-reconcile",
            repo_root=git_repo,
            scope_identity="scope",
        )
        == "reconcile-launches"
    )

    attached = review_feedback.mark_slot_running(
        awaiting,
        "simplicity",
        job_id="simplicity-attempt-2",
        attempt=2,
    )
    assert attached["reviewer_slots"]["simplicity"]["status"] == "running"
    assert attached["pending_action"] == "await-reviewer-decision"
    assert attached["reviewer_decision_slot"] == "bugs"


def test_cli_resume_exposes_pending_running_and_retryable_reviewer_slots(
    git_repo: Path,
):
    scope = {"task": "resume reviewer work"}
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, scope, snapshot=snapshot, cycle_id="slot-resume"
    )
    state_dir = git_state_dir(git_repo)
    state_path = review_feedback.create_state_dir(state_dir, state)
    state = review_feedback.begin_round(state, snapshot)
    state = start_slot(state, "simplicity", job_id="job-simplicity")
    state = start_slot(state, "conventions", job_id="job-conventions-1")
    state = review_feedback.mark_slot_result(
        state,
        "conventions",
        succeeded=False,
        output_path=None,
        attempt=state["reviewer_slots"]["conventions"]["attempt"],
    )
    review_feedback.atomic_write_json(state_path, state)

    completed = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "resume",
            "--state",
            str(state_path),
            "--cycle-id",
            "slot-resume",
            "--scope-json",
            json.dumps(scope),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    resumed = json.loads(completed.stdout)
    assert resumed["action"] == "run-reviewers"
    assert set(resumed["launch_slots"]) == {"bugs", "conventions"}
    assert resumed["collect_slots"] == ["simplicity"]
    assert resumed["reviewer_slots"]["bugs"]["status"] == "pending"
    assert resumed["reviewer_slots"]["simplicity"] == {
        "status": "running",
        "attempt": 1,
        "job_id": "job-simplicity",
        "output_path": None,
        "output_digest": None,
        "waiver_reason": None,
    }
    assert resumed["reviewer_slots"]["conventions"]["status"] == "failed"
    assert resumed["reviewer_slots"]["conventions"]["attempt"] == 1
    assert resumed["reviewer_slots"]["conventions"]["job_id"] == ("job-conventions-1")


def test_reviewed_round_requires_both_empty_ledgers_and_explicit_consolidation(
    git_repo: Path, tmp_path: Path
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    scope = {"task": "empty review consolidation"}
    state = review_feedback.initialize_state(
        git_repo, scope, snapshot=snapshot, cycle_id="empty-consolidation"
    )
    state = review_feedback.begin_round(state, snapshot)
    cycle_dir = tmp_path / "cycle"
    round_dir = cycle_dir / "round-1"
    round_dir.mkdir(parents=True)
    for slot in review_feedback.REVIEWER_SLOTS:
        output = round_dir / f"{slot}.md"
        output.write_text(f"{slot}: no findings\n", encoding="utf-8")
        state = start_slot(state, slot, job_id=f"job-{slot}")
        state = review_feedback.mark_slot_result(
            state,
            slot,
            succeeded=True,
            output_path=f"round-1/{slot}.md",
            attempt=state["reviewer_slots"][slot]["attempt"],
            output_digest=hashlib.sha256(output.read_bytes()).hexdigest(),
            state_dir=cycle_dir,
        )

    reviewed = review_feedback.mark_round_reviewed(state, snapshot, cycle_dir=cycle_dir)

    assert reviewed["pending_action"] == "consolidate-round"
    assert reviewed["round_results"] == {
        "round": 1,
        "gaps_recorded": False,
        "findings_recorded": False,
    }
    assert (
        review_feedback.resume_action(
            reviewed,
            cycle_id="empty-consolidation",
            repo_root=git_repo,
            scope_identity=scope,
        )
        == "consolidate-round"
    )
    with pytest.raises(review_feedback.StateError):
        review_feedback.finalize_for_persistence(reviewed, snapshot)

    with_gaps = review_feedback.record_requirement_gaps(reviewed, [])
    assert with_gaps["round_results"]["gaps_recorded"] is True
    with pytest.raises(review_feedback.StateError):
        review_feedback.consolidate_review_round(with_gaps)

    with_findings = review_feedback.record_verified_findings(with_gaps, [])
    assert with_findings["round_results"]["findings_recorded"] is True
    with pytest.raises(review_feedback.StateError):
        review_feedback.finalize_for_persistence(with_findings, snapshot)

    consolidated = review_feedback.consolidate_review_round(with_findings)

    assert consolidated["round_consolidated"] == 1
    assert consolidated["phase"] == "decision"
    assert consolidated["pending_action"] == "await-user-decision"
    terminal = review_feedback.finalize_for_persistence(consolidated, snapshot)
    assert terminal["status"] == "terminal-pending-persistence"


def test_begin_round_increments_once_only_from_launch(git_repo: Path):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )

    round_one = review_feedback.begin_round(state, snapshot)

    assert state["round"] == 0
    assert round_one["round"] == 1
    assert round_one["pending_action"] == "run-reviewers"
    assert set(round_one["reviewer_slots"]) == set(review_feedback.REVIEWER_SLOTS)
    with pytest.raises(
        review_feedback.StateError, match="requires active launch-round"
    ):
        review_feedback.begin_round(round_one, snapshot)


def test_reviewer_slot_resume_preserves_attempt_count(git_repo: Path, tmp_path: Path):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state = review_feedback.begin_round(state, snapshot)
    state = start_slot(state, "bugs", job_id="job-1")
    state = review_feedback.mark_slot_result(
        state,
        "bugs",
        succeeded=False,
        output_path=None,
        attempt=state["reviewer_slots"]["bugs"]["attempt"],
    )
    state = start_slot(state, "bugs", job_id="job-2")
    state_dir = tmp_path / "state"
    output = state_dir / "round-1" / "bugs.md"
    output.parent.mkdir(parents=True)
    output.write_text("review output\n", encoding="utf-8")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    state = review_feedback.mark_slot_result(
        state,
        "bugs",
        succeeded=True,
        output_path="round-1/bugs.md",
        attempt=state["reviewer_slots"]["bugs"]["attempt"],
        output_digest=digest,
        state_dir=state_dir,
    )

    assert state["round"] == 1
    assert state["reviewer_slots"]["bugs"] == {
        "status": "completed",
        "attempt": 2,
        "job_id": "job-2",
        "output_path": "round-1/bugs.md",
        "output_digest": digest,
        "waiver_reason": None,
    }


def test_reviewer_retry_and_waiver_preserve_resume_action_and_attempts(
    git_repo: Path,
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state = review_feedback.begin_round(state, snapshot)
    for attempt in (1, 2):
        state = start_slot(state, "bugs", job_id=f"job-{attempt}")
        state = review_feedback.mark_slot_result(
            state,
            "bugs",
            succeeded=False,
            output_path=None,
            attempt=state["reviewer_slots"]["bugs"]["attempt"],
        )

    awaiting = review_feedback.set_await_reviewer_decision(state, "bugs")

    assert (
        review_feedback.resume_action(
            awaiting,
            cycle_id="cycle-a",
            repo_root=git_repo,
            scope_identity="scope",
        )
        == "await-reviewer-decision"
    )
    assert awaiting["reviewer_decision_slot"] == "bugs"
    assert awaiting["reviewer_slots"]["bugs"]["attempt"] == 2

    retrying = review_feedback.prepare_reviewer_retry(awaiting, "bugs")

    assert (
        review_feedback.resume_action(
            retrying,
            cycle_id="cycle-a",
            repo_root=git_repo,
            scope_identity="scope",
        )
        == "retry-reviewer"
    )
    assert retrying["reviewer_decision_slot"] == "bugs"
    assert retrying["reviewer_slots"]["bugs"]["attempt"] == 2

    retry_running = start_slot(retrying, "bugs", job_id="job-3")

    assert (
        review_feedback.resume_action(
            retry_running,
            cycle_id="cycle-a",
            repo_root=git_repo,
            scope_identity="scope",
        )
        == "run-reviewers"
    )
    assert retry_running["reviewer_decision_slot"] is None
    assert retry_running["reviewer_slots"]["bugs"]["attempt"] == 3

    waived = review_feedback.waive_slot(
        awaiting, "bugs", reason="사용자가 해당 관점 누락을 승인했습니다."
    )

    assert (
        review_feedback.resume_action(
            waived,
            cycle_id="cycle-a",
            repo_root=git_repo,
            scope_identity="scope",
        )
        == "run-reviewers"
    )
    assert waived["reviewer_decision_slot"] is None
    assert waived["reviewer_slots"]["bugs"]["status"] == "waived"
    assert waived["reviewer_slots"]["bugs"]["attempt"] == 2


def test_twice_failed_reviewer_cannot_start_third_attempt_without_decision(
    git_repo: Path,
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="retry-gate"
    )
    state = review_feedback.begin_round(state, snapshot)
    for attempt in (1, 2):
        state = start_slot(state, "bugs", job_id=f"job-{attempt}")
        state = review_feedback.mark_slot_result(
            state,
            "bugs",
            succeeded=False,
            output_path=None,
            attempt=state["reviewer_slots"]["bugs"]["attempt"],
        )
    before = deepcopy(state)

    with pytest.raises(review_feedback.StateError):
        review_feedback.reserve_launches(state, ["bugs"])

    assert state == before
    assert state["reviewer_slots"]["bugs"]["attempt"] == 2
    awaiting = review_feedback.set_await_reviewer_decision(state, "bugs")
    retrying = review_feedback.prepare_reviewer_retry(awaiting, "bugs")
    third_attempt = start_slot(retrying, "bugs", job_id="job-3")
    assert third_attempt["reviewer_slots"]["bugs"]["attempt"] == 3


def test_await_user_state_survives_atomic_save_and_resume(git_repo: Path):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    scope = {"task": "wait"}
    state = review_feedback.initialize_state(
        git_repo, scope, snapshot=snapshot, cycle_id="cycle-wait"
    )
    state_path = review_feedback.create_state_dir(git_state_dir(git_repo), state)
    state = complete_round(state, snapshot, state_path.parent)
    state = review_feedback.set_await_user_decision(state)
    review_feedback.atomic_write_json(state_path, state)

    loaded = review_feedback.read_state(state_path)

    assert file_mode(state_path) == 0o600
    assert (
        review_feedback.resume_action(
            loaded,
            cycle_id="cycle-wait",
            repo_root=git_repo,
            scope_identity=scope,
        )
        == "await-user-decision"
    )
    with pytest.raises(review_feedback.StateError, match="already exists"):
        review_feedback.create_state_dir(state_path.parent, state)


def test_dedupe_uses_root_cause_id_not_shared_file_line():
    first = make_finding("root-a", rule="첫 번째 원인을 방지합니다.")
    second = make_finding("root-b", rule="두 번째 원인을 방지합니다.")
    first["evidence"] = second["evidence"] = "src/example.py:42"

    deduped = review_feedback.dedupe_findings([first, second])

    assert [item["id"] for item in deduped] == ["root-a", "root-b"]


def test_finalize_requires_final_dispositions_for_gaps_and_findings(
    git_repo: Path, tmp_path: Path
):
    (git_repo / "tracked.txt").write_text("reviewed change\n", encoding="utf-8")
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state = complete_round(state, snapshot, tmp_path / "cycle")
    state["findings"] = [make_finding(disposition="open")]
    state["requirement_gaps"] = [
        {"id": "gap-a", "severity": "critical", "disposition": "false-positive"}
    ]

    with pytest.raises(review_feedback.StateError, match="lacks final disposition"):
        review_feedback.finalize_for_persistence(state, snapshot)

    state["findings"][0]["disposition"] = "false-positive"
    state["requirement_gaps"][0]["disposition"] = "open"
    with pytest.raises(review_feedback.StateError, match="lacks final disposition"):
        review_feedback.finalize_for_persistence(state, snapshot)


@pytest.mark.parametrize("severity", ("critical", "warning"))
@pytest.mark.parametrize("disposition", ("사용자 수용", "보류"))
def test_blocker_acceptance_or_deferral_requires_apply_decisions_provenance(
    git_repo: Path,
    tmp_path: Path,
    severity: str,
    disposition: str,
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo,
        "scope",
        snapshot=snapshot,
        cycle_id=f"decision-{severity}",
    )
    finding = make_finding(
        f"{severity}-finding",
        disposition=disposition,
        severity=severity,
        reusable=False,
    )
    state = complete_round(
        state,
        snapshot,
        tmp_path / "cycle",
        findings=[finding],
    )
    before = deepcopy(state)

    with pytest.raises(review_feedback.StateError, match="user decision|provenance"):
        review_feedback.finalize_for_persistence(state, snapshot)

    assert state == before
    decided = review_feedback.apply_user_decisions(state, {finding["id"]: disposition})
    terminal = review_feedback.finalize_for_persistence(decided, snapshot)
    assert terminal["status"] == "terminal-pending-persistence"


@pytest.mark.parametrize(
    ("drift", "message"),
    (
        ("commit", "HEAD changed"),
        ("new-path", "path scope drifted"),
        ("post-review-edit", "content changed after"),
    ),
)
def test_finalize_rejects_commit_path_and_content_drift(
    git_repo: Path, tmp_path: Path, drift: str, message: str
):
    (git_repo / "tracked.txt").write_text("reviewed change\n", encoding="utf-8")
    reviewed = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=reviewed, cycle_id="cycle-a"
    )
    state = complete_round(state, reviewed, tmp_path / "cycle")
    state["findings"] = [make_finding()]

    if drift == "commit":
        run_git(git_repo, "add", "tracked.txt")
        run_git(git_repo, "commit", "-qm", "mid-cycle")
    elif drift == "new-path":
        (git_repo / "new.py").write_text("new\n", encoding="utf-8")
    else:
        (git_repo / "tracked.txt").write_text("edited after review\n", encoding="utf-8")

    current = review_feedback.capture_repo_snapshot(git_repo)
    with pytest.raises(review_feedback.StateError, match=message):
        review_feedback.finalize_for_persistence(state, current)


def test_persistable_allowlist_excludes_open_false_positive_and_nonreusable(
    git_repo: Path,
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    finals = ["해결됨", "사용자 수용", "보류", "제안됨"]
    state["findings"] = [
        make_finding(f"final-{index}", disposition=disposition)
        for index, disposition in enumerate(finals)
    ]
    state["findings"] += [
        make_finding("open", disposition="open"),
        make_finding("false", disposition="false-positive"),
        make_finding("nonreusable", disposition="해결됨", reusable=False),
    ]

    selected = review_feedback.select_persistable_findings(state)

    assert [item["disposition"] for item in selected] == finals
    assert {item["id"] for item in selected}.isdisjoint(
        {"open", "false", "nonreusable"}
    )


def test_capture_snapshot_includes_tracked_edits_and_untracked_files(git_repo: Path):
    (git_repo / "tracked.txt").write_text("tracked edit\n", encoding="utf-8")
    (git_repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    first = review_feedback.capture_repo_snapshot(git_repo)
    (git_repo / "untracked.txt").write_text("changed untracked\n", encoding="utf-8")
    second = review_feedback.capture_repo_snapshot(git_repo)

    assert first["paths"] == ["tracked.txt", "untracked.txt"]
    assert second["paths"] == first["paths"]
    assert second["fingerprint"] != first["fingerprint"]


def test_snapshot_distinguishes_index_only_changes_with_identical_worktree(
    git_repo: Path,
):
    tracked = git_repo / "tracked.txt"
    tracked.write_text("staged one\n", encoding="utf-8")
    run_git(git_repo, "add", "tracked.txt")
    tracked.write_text("same worktree\n", encoding="utf-8")
    staged_one = review_feedback.capture_repo_snapshot(git_repo)

    tracked.write_text("staged two\n", encoding="utf-8")
    run_git(git_repo, "add", "tracked.txt")
    tracked.write_text("same worktree\n", encoding="utf-8")
    staged_two = review_feedback.capture_repo_snapshot(git_repo)

    assert staged_one["paths"] == staged_two["paths"] == ["tracked.txt"]
    assert staged_one["entries"] == staged_two["entries"]
    assert staged_one["index_fingerprint"] != staged_two["index_fingerprint"]
    assert staged_one["fingerprint"] != staged_two["fingerprint"]


def test_snapshot_detects_intent_to_add_for_same_untracked_file(git_repo: Path):
    untracked = git_repo / "intent.py"
    untracked.write_text("same content\n", encoding="utf-8")
    before = review_feedback.capture_repo_snapshot(git_repo)

    run_git(git_repo, "add", "-N", "intent.py")
    after = review_feedback.capture_repo_snapshot(git_repo)

    assert before["paths"] == after["paths"] == ["intent.py"]
    assert before["entries"] == after["entries"]
    assert before["index_fingerprint"] != after["index_fingerprint"]
    assert before["fingerprint"] != after["fingerprint"]


def test_missing_document_gets_canonical_scaffold():
    candidate = review_feedback.build_guidance_candidate(
        "", [make_finding()], "AGENTS.md"
    )

    assert candidate.count(review_feedback.HEADING) == 1
    assert candidate.count(review_feedback.START_MARKER) == 1
    assert candidate.count(review_feedback.END_MARKER) == 1
    after_heading = candidate.split(review_feedback.HEADING, 1)[1].lstrip()
    assert after_heading.startswith(review_feedback.START_MARKER)


def test_stable_id_updates_existing_managed_entry():
    original_finding = make_finding(
        "stable-a", rule="이전 규칙입니다.", disposition="보류"
    )
    first = review_feedback.build_guidance_candidate(
        "", [original_finding], "AGENTS.md"
    )
    updated_finding = make_finding(
        "stable-a", rule="새 규칙입니다.", disposition="해결됨"
    )

    updated = review_feedback.build_guidance_candidate(
        first, [updated_finding], "AGENTS.md"
    )

    assert updated.count("feature:codex-review-id:stable-a;") == 1
    assert "이전 규칙입니다." not in updated
    assert "새 규칙입니다." in updated
    assert "Codex 리뷰 2026-07-20, 해결됨" in updated


def test_visible_managed_rule_must_match_its_protected_scope_and_rule_hash():
    finding = make_finding(disposition="제안됨", severity="suggestion")
    original = review_feedback.build_guidance_candidate("", [finding], "AGENTS.md")
    tampered = original.replace(
        finding["rule"],
        "미래 구현에서는 입력 검증을 절대 하지 않습니다.",
    )

    with pytest.raises(
        review_feedback.PersistenceError,
        match="visible managed rule does not match its protected hash",
    ):
        review_feedback.build_guidance_candidate(
            tampered,
            [make_finding("finding-b", disposition="제안됨", severity="suggestion")],
            "AGENTS.md",
        )


@pytest.mark.parametrize(
    "malformed",
    (
        "## Codex 코드 리뷰에서 배운 규칙\n\n## Codex 코드 리뷰에서 배운 규칙\n",
        "## Codex 코드 리뷰에서 배운 규칙\n\n<!-- feature:codex-review-learnings:start -->\n",
        (
            "## Codex 코드 리뷰에서 배운 규칙\n\n"
            "<!-- feature:codex-review-learnings:start -->\n"
            "<!-- feature:codex-review-learnings:start -->\n"
            "<!-- feature:codex-review-learnings:end -->\n"
        ),
        (
            "<!-- feature:codex-review-learnings:start -->\n"
            "<!-- feature:codex-review-learnings:end -->\n"
        ),
        (
            "## Codex 코드 리뷰에서 배운 규칙\n\n"
            "<!-- feature:codex-review-learnings:end -->\n"
            "<!-- feature:codex-review-learnings:start -->\n"
        ),
        (
            "## Codex 코드 리뷰에서 배운 규칙\n\n"
            "unexpected content\n"
            "<!-- feature:codex-review-learnings:start -->\n"
            "<!-- feature:codex-review-learnings:end -->\n"
        ),
    ),
)
def test_malformed_heading_or_markers_fail_closed(malformed: str):
    with pytest.raises(review_feedback.PersistenceError):
        review_feedback.build_guidance_candidate(
            malformed, [make_finding()], "AGENTS.md"
        )


def test_duplicate_managed_semantic_rules_fail_closed():
    first = review_feedback.build_guidance_candidate(
        "", [make_finding("stable-a")], "AGENTS.md"
    )
    line = next(
        raw for raw in first.splitlines() if "feature:codex-review-id:stable-a;" in raw
    )
    duplicate = line.replace(
        "feature:codex-review-id:stable-a;",
        "feature:codex-review-id:stable-b;",
    )
    malformed = first.replace(
        review_feedback.END_MARKER,
        f"{duplicate}\n{review_feedback.END_MARKER}",
    )

    with pytest.raises(
        review_feedback.PersistenceError, match="duplicate managed semantic rule"
    ):
        review_feedback.build_guidance_candidate(
            malformed,
            [make_finding("stable-c", rule="다른 규칙입니다.")],
            "AGENTS.md",
        )


def test_external_anchor_creates_metadata_reference_without_repeating_rule():
    original = "# Existing\n\nEXACT EXTERNAL ANCHOR\n"
    finding = make_finding(
        "external-a",
        rule="관리 블록에 반복하면 안 되는 규칙입니다.",
        disposition="사용자 수용",
        coverage={
            "AGENTS.md": {
                "kind": "external",
                "anchor": "EXACT EXTERNAL ANCHOR",
                "label": "기존 외부 규칙",
            },
            "CLAUDE.md": {"kind": "managed"},
        },
    )

    candidate = review_feedback.build_guidance_candidate(
        original, [finding], "AGENTS.md"
    )

    assert candidate.startswith(original)
    assert finding["rule"] not in candidate
    assert "기존 규칙 참조: 기존 외부 규칙" in candidate
    assert "Codex 리뷰 2026-07-20, 사용자 수용" in candidate
    assert "kind:reference" in candidate


@pytest.mark.parametrize(
    "original",
    (
        "# Existing\n",
        "EXACT ANCHOR\nEXACT ANCHOR\n",
    ),
)
def test_external_anchor_must_exist_exactly_once(original: str):
    finding = make_finding(
        "external-a",
        coverage={
            "AGENTS.md": {
                "kind": "external",
                "anchor": "EXACT ANCHOR",
                "label": "기존 외부 규칙",
            },
            "CLAUDE.md": {"kind": "managed"},
        },
    )

    with pytest.raises(
        review_feedback.PersistenceError, match="must occur exactly once"
    ):
        review_feedback.build_guidance_candidate(original, [finding], "AGENTS.md")


def test_helper_compiles_imports_and_opens_cli_help_on_python39(tmp_path: Path):
    python39 = shutil.which("python3.9")
    if python39 is None:
        uv = shutil.which("uv")
        if uv is not None:
            found = subprocess.run(
                [uv, "python", "find", "3.9"],
                capture_output=True,
                text=True,
            )
            if found.returncode == 0 and Path(found.stdout.strip()).is_file():
                python39 = found.stdout.strip()
    if python39 is None:
        pytest.skip("Python 3.9 interpreter is not installed")

    version = subprocess.run([python39, "--version"], capture_output=True, text=True)
    assert version.returncode == 0
    assert (version.stdout + version.stderr).startswith("Python 3.9.")

    compiled = tmp_path / "review_feedback.pyc"
    check_script = """
import importlib.util
import py_compile
import sys

py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)
spec = importlib.util.spec_from_file_location("feature_review_feedback_py39", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
"""
    checked = subprocess.run(
        [python39, "-c", check_script, str(HELPER_PATH), str(compiled)],
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stderr
    assert compiled.is_file()

    help_result = subprocess.run(
        [python39, str(HELPER_PATH), "--help"],
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "usage:" in help_result.stdout


def test_windows_lock_branch_locks_unlocks_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    windows_locking = FakeWindowsLocking()
    monkeypatch.setattr(review_feedback, "fcntl", None)
    monkeypatch.setattr(review_feedback, "msvcrt", windows_locking, raising=False)

    with review_feedback._persistence_lock(tmp_path):
        assert (tmp_path.parent / f".{tmp_path.name}.lock").read_bytes() == b"\0"

    descriptor = windows_locking.calls[0][0]
    assert [
        (mode, length, position) for _, mode, length, position in windows_locking.calls
    ] == [
        (windows_locking.LK_LOCK, 1, 0),
        (windows_locking.LK_UNLCK, 1, 0),
    ]
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_windows_lock_acquire_failure_does_not_unlock_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    windows_locking = FakeWindowsLocking(fail_mode=FakeWindowsLocking.LK_LOCK)
    monkeypatch.setattr(review_feedback, "fcntl", None)
    monkeypatch.setattr(review_feedback, "msvcrt", windows_locking, raising=False)

    with pytest.raises(OSError, match="injected Windows lock failure"):
        with review_feedback._persistence_lock(tmp_path):
            pytest.fail("an unacquired lock must never enter its protected body")

    descriptor = windows_locking.calls[0][0]
    assert [mode for _, mode, _, _ in windows_locking.calls] == [
        windows_locking.LK_LOCK
    ]
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_windows_unlock_failure_still_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    windows_locking = FakeWindowsLocking(fail_mode=FakeWindowsLocking.LK_UNLCK)
    monkeypatch.setattr(review_feedback, "fcntl", None)
    monkeypatch.setattr(review_feedback, "msvcrt", windows_locking, raising=False)

    with pytest.raises(OSError, match="injected Windows lock failure"):
        with review_feedback._persistence_lock(tmp_path):
            pass

    descriptor = windows_locking.calls[0][0]
    assert [mode for _, mode, _, _ in windows_locking.calls] == [
        windows_locking.LK_LOCK,
        windows_locking.LK_UNLCK,
    ]
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_linux_noreplace_uses_raw_syscall_when_libc_wrapper_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class FakeSyscall:
        restype = None

        def __init__(self):
            self.calls: list[tuple] = []

        def __call__(self, *args) -> int:
            self.calls.append(args)
            return 0

    class FakeLibc:
        def __init__(self):
            self.syscall = FakeSyscall()

    class FakeUname:
        machine = "x86_64"

    libc = FakeLibc()
    monkeypatch.setattr(review_feedback.sys, "platform", "linux")
    monkeypatch.setattr(
        review_feedback.ctypes,
        "CDLL",
        lambda *_args, **_kwargs: libc,
    )
    monkeypatch.setattr(review_feedback.os, "uname", lambda: FakeUname())

    review_feedback._rename_noreplace(tmp_path / "source", tmp_path / "target")

    assert len(libc.syscall.calls) == 1
    assert libc.syscall.calls[0][0].value == 316
    assert libc.syscall.restype is review_feedback.ctypes.c_long


def test_persist_creates_missing_targets_with_0644_and_removes_temps(
    git_repo: Path,
):
    state_path = write_ready_state(git_repo, [make_finding()], cycle_id="create-docs")

    result = review_feedback.persist_feedback(state_path)

    assert result["changed"] is True
    for name in review_feedback.TARGET_NAMES:
        target = git_repo / name
        text = target.read_text(encoding="utf-8")
        assert file_mode(target) == 0o644
        assert text.count(review_feedback.HEADING) == 1
        assert text.count(review_feedback.START_MARKER) == 1
        assert text.count(review_feedback.END_MARKER) == 1
        assert not list(git_repo.glob(f".{name}.feature-review-create-docs.*"))


def test_persist_preserves_existing_content_and_modes(git_repo: Path):
    originals = {
        "AGENTS.md": b"# Agents\n\nkeep agents bytes\n",
        "CLAUDE.md": b"# Claude\n\nkeep claude bytes\n",
    }
    modes = {"AGENTS.md": 0o640, "CLAUDE.md": 0o600}
    for name, data in originals.items():
        (git_repo / name).write_bytes(data)
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    for name, mode in modes.items():
        os.chmod(git_repo / name, mode)
    state_path = write_ready_state(git_repo, [make_finding()])

    review_feedback.persist_feedback(state_path)

    for name, original in originals.items():
        assert (git_repo / name).read_bytes().startswith(original)
        assert file_mode(git_repo / name) == modes[name]


def test_persist_preserves_staged_guidance_edit_after_final_review(git_repo: Path):
    for name in review_feedback.TARGET_NAMES:
        (git_repo / name).write_text(f"# {name}\n", encoding="utf-8")
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    state_path = write_ready_state(
        git_repo,
        [make_finding(disposition="사용자 수용")],
        cycle_id="staged-guidance",
    )
    agents = git_repo / "AGENTS.md"
    agents.write_text("# AGENTS.md\n\nuser staged rule\n", encoding="utf-8")
    run_git(git_repo, "add", "AGENTS.md")

    result = review_feedback.persist_feedback(state_path)

    assert result["changed"] is True
    assert "user staged rule" in agents.read_text(encoding="utf-8")
    assert review_feedback.START_MARKER in agents.read_text(encoding="utf-8")
    assert run_git(git_repo, "show", ":AGENTS.md") == "# AGENTS.md\n\nuser staged rule"


def test_persist_rejects_staged_non_guidance_edit_after_final_review(git_repo: Path):
    state_path = write_ready_state(
        git_repo,
        [make_finding(disposition="사용자 수용")],
        cycle_id="staged-code-drift",
    )
    (git_repo / "tracked.txt").write_text("staged after review\n", encoding="utf-8")
    run_git(git_repo, "add", "tracked.txt")

    with pytest.raises(review_feedback.StateError, match="non-guidance Git index"):
        review_feedback.persist_feedback(state_path)

    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )


def test_non_guidance_change_at_candidates_ready_rolls_back_and_keeps_terminal(
    git_repo: Path,
):
    originals = {
        "AGENTS.md": b"agents original\n",
        "CLAUDE.md": b"claude original\n",
    }
    for name, data in originals.items():
        (git_repo / name).write_bytes(data)
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    state_path = write_ready_state(
        git_repo,
        [make_finding(disposition="사용자 수용")],
        cycle_id="candidate-drift",
    )

    def inject_non_guidance_change(event: str, _context: dict):
        if event == "candidates-ready":
            (git_repo / "tracked.txt").write_text(
                "changed after candidates were prepared\n", encoding="utf-8"
            )

    with pytest.raises(review_feedback.StateError, match="non-guidance"):
        review_feedback.persist_feedback(state_path, hook=inject_non_guidance_change)

    assert (git_repo / "tracked.txt").read_text(encoding="utf-8") == (
        "changed after candidates were prepared\n"
    )
    for name, original in originals.items():
        target = git_repo / name
        assert target.read_bytes() == original
        assert not review_feedback._artifact_path(
            target, "candidate-drift", "candidate"
        ).exists()
        assert not review_feedback._artifact_path(
            target, "candidate-drift", "original"
        ).exists()
    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )


def test_guidance_change_after_verified_is_caught_before_state_commit(
    git_repo: Path,
):
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id="verified-guidance-drift",
    )
    agents = git_repo / "AGENTS.md"

    def remove_verified_target(event: str, _context: dict) -> None:
        if event == "verified":
            agents.unlink()

    with pytest.raises(
        review_feedback.PersistenceError,
        match="target changed before state commit",
    ):
        review_feedback.persist_feedback(state_path, hook=remove_verified_target)

    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )
    assert not agents.exists()
    assert not (git_repo / "CLAUDE.md").exists()
    for name in review_feedback.TARGET_NAMES:
        assert not list(
            git_repo.glob(f".{name}.feature-review-verified-guidance-drift.*")
        )

    assert review_feedback.persist_feedback(state_path)["changed"] is True


def test_second_replace_failure_rolls_back_first_bytes_and_mode(
    git_repo: Path,
):
    originals = {"AGENTS.md": b"agents original\n", "CLAUDE.md": b"claude original\n"}
    modes = {"AGENTS.md": 0o640, "CLAUDE.md": 0o600}
    for name, data in originals.items():
        (git_repo / name).write_bytes(data)
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    for name, mode in modes.items():
        os.chmod(git_repo / name, mode)
    state_path = write_ready_state(git_repo, [make_finding()])
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second replace failure")
        os.replace(source, target)

    with pytest.raises(review_feedback.PersistenceError, match="rolled back"):
        review_feedback.persist_feedback(state_path, replace=fail_second_replace)

    assert calls == 2
    for name, original in originals.items():
        assert (git_repo / name).read_bytes() == original
        assert file_mode(git_repo / name) == modes[name]


def test_replace_that_moves_then_raises_rolls_back_and_remains_retryable(
    git_repo: Path,
):
    originals = {
        "AGENTS.md": b"agents original\n",
        "CLAUDE.md": b"claude original\n",
    }
    modes = {"AGENTS.md": 0o640, "CLAUDE.md": 0o600}
    for name, data in originals.items():
        (git_repo / name).write_bytes(data)
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    for name, mode in modes.items():
        os.chmod(git_repo / name, mode)
    state_path = write_ready_state(
        git_repo,
        [make_finding(disposition="사용자 수용")],
        cycle_id="move-then-raise",
    )
    calls = 0

    def move_then_raise(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        os.replace(source, target)
        raise OSError("injected exception after successful move")

    with pytest.raises(review_feedback.PersistenceError, match="rolled back"):
        review_feedback.persist_feedback(state_path, replace=move_then_raise)

    assert calls == 1
    for name, original in originals.items():
        target = git_repo / name
        assert target.read_bytes() == original
        assert file_mode(target) == modes[name]
        assert not review_feedback._artifact_path(
            target, "move-then-raise", "candidate"
        ).exists()
        assert not review_feedback._artifact_path(
            target, "move-then-raise", "original"
        ).exists()
    terminal = review_feedback.read_state(state_path)
    assert terminal["status"] == "terminal-pending-persistence"
    assert terminal["pending_action"] == "persist-feedback"

    retried = review_feedback.persist_feedback(state_path)

    assert retried["changed"] is True
    assert review_feedback.read_state(state_path)["status"] == "complete"
    for name, mode in modes.items():
        assert file_mode(git_repo / name) == mode


def test_concurrent_second_target_edit_is_preserved_and_first_rolls_back(
    git_repo: Path,
):
    agents = git_repo / "AGENTS.md"
    claude = git_repo / "CLAUDE.md"
    agents.write_text("agents original\n", encoding="utf-8")
    claude.write_text("claude original\n", encoding="utf-8")
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    state_path = write_ready_state(git_repo, [make_finding()])

    def concurrent_edit(event: str, _context: dict):
        if event == "after-replace:AGENTS.md":
            claude.write_text("concurrent user edit\n", encoding="utf-8")

    with pytest.raises(review_feedback.PersistenceError, match="target changed"):
        review_feedback.persist_feedback(state_path, hook=concurrent_edit)

    assert agents.read_text(encoding="utf-8") == "agents original\n"
    assert claude.read_text(encoding="utf-8") == "concurrent user edit\n"


def test_tampered_original_artifact_is_never_used_for_rollback(git_repo: Path):
    agents = git_repo / "AGENTS.md"
    claude = git_repo / "CLAUDE.md"
    agents.write_text("agents original\n", encoding="utf-8")
    claude.write_text("claude original\n", encoding="utf-8")
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id="tampered-original",
    )
    original = review_feedback._artifact_path(agents, "tampered-original", "original")
    foreign = b"foreign artifact contents\n"

    def tamper_transaction(event: str, _context: dict) -> None:
        if event == "after-replace:AGENTS.md":
            original.write_bytes(foreign)
            claude.write_text("concurrent user edit\n", encoding="utf-8")

    with pytest.raises(
        review_feedback.PersistenceError,
        match="partial rollback.*original artifact changed unexpectedly",
    ):
        review_feedback.persist_feedback(state_path, hook=tamper_transaction)

    assert agents.read_bytes() != foreign
    assert review_feedback.START_MARKER.encode() in agents.read_bytes()
    assert claude.read_text(encoding="utf-8") == "concurrent user edit\n"
    assert original.read_bytes() == foreign
    assert review_feedback._artifact_path(
        agents, "tampered-original", "candidate"
    ).is_file()
    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )


def test_rerun_recovers_legacy_rollback_link_state_and_cleanup_failure(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    originals = {
        "AGENTS.md": b"agents original\n",
        "CLAUDE.md": b"claude original\n",
    }
    for name, data in originals.items():
        (git_repo / name).write_bytes(data)
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id="rollback-link-interrupt",
    )
    agents = git_repo / "AGENTS.md"
    agents_original = review_feedback._artifact_path(
        agents, "rollback-link-interrupt", "original"
    )
    crashed = crash_persist_at(state_path, "before-publish:AGENTS.md", 78)
    assert crashed.returncode == 78, crashed.stderr
    assert not agents.exists()
    os.link(agents_original, agents)

    assert agents.read_bytes() == originals["AGENTS.md"]
    assert agents_original.read_bytes() == originals["AGENTS.md"]
    assert os.path.samefile(agents, agents_original)

    real_unlink_artifact = review_feedback._unlink_artifact
    fail_original_cleanup = True

    def reject_original_cleanup(path: Path, data: bytes, mode: int) -> None:
        nonlocal fail_original_cleanup
        if fail_original_cleanup and path == agents_original:
            fail_original_cleanup = False
            raise OSError("injected restored-original cleanup failure")
        real_unlink_artifact(path, data, mode)

    monkeypatch.setattr(review_feedback, "_unlink_artifact", reject_original_cleanup)
    with pytest.raises(
        review_feedback.PersistenceError,
        match="rollback cleanup failed.*original artifact remains",
    ):
        review_feedback.persist_feedback(state_path)

    agents_candidate = review_feedback._artifact_path(
        agents, "rollback-link-interrupt", "candidate"
    )
    assert agents_original.is_file()
    assert agents_candidate.is_file()

    monkeypatch.setattr(review_feedback, "_unlink_artifact", real_unlink_artifact)
    result = review_feedback.persist_feedback(state_path)

    assert result["changed"] is True
    assert review_feedback.read_state(state_path)["status"] == "complete"
    for name in review_feedback.TARGET_NAMES:
        assert not list(
            git_repo.glob(f".{name}.feature-review-rollback-link-interrupt.*")
        )


def test_concurrent_original_artifact_creation_is_preserved_without_clobber(
    git_repo: Path,
):
    originals = {
        "AGENTS.md": b"agents original\n",
        "CLAUDE.md": b"claude original\n",
    }
    for name, data in originals.items():
        (git_repo / name).write_bytes(data)
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id="original-create-race",
    )
    foreign = b"foreign concurrent artifact\n"
    raced = False

    def create_destination_then_move(source: Path, target: Path) -> None:
        nonlocal raced
        if not raced:
            raced = True
            target.write_bytes(foreign)
        review_feedback._rename_noreplace(source, target)

    with pytest.raises(
        review_feedback.PersistenceError,
        match="rollback cleanup failed.*original artifact remains",
    ):
        review_feedback.persist_feedback(
            state_path,
            replace=create_destination_then_move,
        )

    assert raced is True
    for name, data in originals.items():
        assert (git_repo / name).read_bytes() == data
    agents_original = review_feedback._artifact_path(
        git_repo / "AGENTS.md", "original-create-race", "original"
    )
    assert agents_original.read_bytes() == foreign
    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )


def test_source_type_race_is_restored_to_its_original_target_path(git_repo: Path):
    agents = git_repo / "AGENTS.md"
    claude = git_repo / "CLAUDE.md"
    replacement = git_repo / "replacement.txt"
    agents.write_text("agents original\n", encoding="utf-8")
    claude.write_text("claude original\n", encoding="utf-8")
    replacement.write_text("replacement target\n", encoding="utf-8")
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md", "replacement.txt")
    run_git(git_repo, "commit", "-qm", "add guidance and replacement")
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id="source-type-race",
    )
    raced = False

    def replace_source_then_move(source: Path, target: Path) -> None:
        nonlocal raced
        if not raced:
            raced = True
            source.unlink()
            source.symlink_to(replacement.name)
        review_feedback._rename_noreplace(source, target)

    with pytest.raises(
        review_feedback.PersistenceError,
        match="guidance target is not a regular file",
    ):
        review_feedback.persist_feedback(
            state_path,
            replace=replace_source_then_move,
        )

    assert raced is True
    assert agents.is_symlink()
    assert os.readlink(agents) == replacement.name
    assert claude.read_text(encoding="utf-8") == "claude original\n"
    for name in review_feedback.TARGET_NAMES:
        assert not list(git_repo.glob(f".{name}.feature-review-source-type-race.*"))
    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )


def test_rollback_restores_a_concurrent_user_target_without_unlinking(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    agents = git_repo / "AGENTS.md"
    claude = git_repo / "CLAUDE.md"
    replacement = git_repo / "replacement.txt"
    agents.write_text("agents original\n", encoding="utf-8")
    claude.write_text("claude original\n", encoding="utf-8")
    replacement.write_text("replacement target\n", encoding="utf-8")
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md", "replacement.txt")
    run_git(git_repo, "commit", "-qm", "add guidance and replacement")
    cycle_id = "rollback-target-race"
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id=cycle_id,
    )
    rollback_path = review_feedback._artifact_path(agents, cycle_id, "rollback")
    real_rename_noreplace = review_feedback._rename_noreplace
    raced = False

    def replace_target_at_rollback(source: Path, target: Path) -> None:
        nonlocal raced
        if Path(source) == agents and Path(target) == rollback_path:
            raced = True
            agents.unlink()
            agents.symlink_to(replacement.name)
        real_rename_noreplace(source, target)

    def force_rollback(event: str, _context: dict) -> None:
        if event == "after-replace:AGENTS.md":
            claude.write_text("concurrent user edit\n", encoding="utf-8")

    monkeypatch.setattr(
        review_feedback, "_rename_noreplace", replace_target_at_rollback
    )
    with pytest.raises(
        review_feedback.PersistenceError,
        match="partial rollback.*current content is no longer our candidate",
    ):
        review_feedback.persist_feedback(state_path, hook=force_rollback)

    assert raced is True
    assert agents.is_symlink()
    assert os.readlink(agents) == replacement.name
    assert claude.read_text(encoding="utf-8") == "concurrent user edit\n"
    assert not rollback_path.exists()
    assert review_feedback._artifact_path(agents, cycle_id, "candidate").is_file()
    assert review_feedback._artifact_path(agents, cycle_id, "original").is_file()
    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )


def test_restart_restores_a_nonregular_source_moved_before_process_crash(
    git_repo: Path,
):
    agents = git_repo / "AGENTS.md"
    claude = git_repo / "CLAUDE.md"
    replacement = git_repo / "replacement.txt"
    agents.write_text("agents original\n", encoding="utf-8")
    claude.write_text("claude original\n", encoding="utf-8")
    replacement.write_text("replacement target\n", encoding="utf-8")
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md", "replacement.txt")
    run_git(git_repo, "commit", "-qm", "add guidance and replacement")
    cycle_id = "source-type-crash"
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id=cycle_id,
    )
    crashed = crash_persist_at(state_path, "candidates-ready", 79)
    assert crashed.returncode == 79, crashed.stderr

    candidate_path = review_feedback._artifact_path(agents, cycle_id, "candidate")
    original_path = review_feedback._artifact_path(agents, cycle_id, "original")
    agents.unlink()
    agents.symlink_to(replacement.name)
    review_feedback._rename_noreplace(agents, original_path)

    with pytest.raises(
        review_feedback.PersistenceError,
        match="nonregular moved artifact restored to target",
    ):
        review_feedback.persist_feedback(state_path)

    assert agents.is_symlink()
    assert os.readlink(agents) == replacement.name
    assert not original_path.exists()
    assert candidate_path.is_file()
    assert claude.read_text(encoding="utf-8") == "claude original\n"
    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )


def test_restart_recovers_a_candidate_parked_during_rollback(git_repo: Path):
    originals = {
        "AGENTS.md": b"agents original\n",
        "CLAUDE.md": b"claude original\n",
    }
    for name, data in originals.items():
        (git_repo / name).write_bytes(data)
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    cycle_id = "rollback-park-crash"
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id=cycle_id,
    )
    crashed = crash_persist_at(state_path, "after-replace:AGENTS.md", 80)
    assert crashed.returncode == 80, crashed.stderr

    agents = git_repo / "AGENTS.md"
    rollback_path = review_feedback._artifact_path(agents, cycle_id, "rollback")
    review_feedback._rename_noreplace(agents, rollback_path)
    assert not agents.exists()

    result = review_feedback.persist_feedback(state_path)

    assert result["changed"] is True
    assert review_feedback.read_state(state_path)["status"] == "complete"
    for name in review_feedback.TARGET_NAMES:
        assert review_feedback.START_MARKER in (git_repo / name).read_text(
            encoding="utf-8"
        )
        assert not list(git_repo.glob(f".{name}.feature-review-{cycle_id}.*"))


def test_restart_restores_a_changed_target_parked_during_rollback(git_repo: Path):
    agents = git_repo / "AGENTS.md"
    claude = git_repo / "CLAUDE.md"
    replacement = git_repo / "replacement.txt"
    agents.write_text("agents original\n", encoding="utf-8")
    claude.write_text("claude original\n", encoding="utf-8")
    replacement.write_text("replacement target\n", encoding="utf-8")
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md", "replacement.txt")
    run_git(git_repo, "commit", "-qm", "add guidance and replacement")
    cycle_id = "changed-rollback-crash"
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id=cycle_id,
    )
    crashed = crash_persist_at(state_path, "after-replace:AGENTS.md", 81)
    assert crashed.returncode == 81, crashed.stderr

    rollback_path = review_feedback._artifact_path(agents, cycle_id, "rollback")
    original_path = review_feedback._artifact_path(agents, cycle_id, "original")
    candidate_path = review_feedback._artifact_path(agents, cycle_id, "candidate")
    agents.unlink()
    agents.symlink_to(replacement.name)
    review_feedback._rename_noreplace(agents, rollback_path)

    with pytest.raises(
        review_feedback.PersistenceError,
        match="changed rollback artifact restored to target",
    ):
        review_feedback.persist_feedback(state_path)

    assert agents.is_symlink()
    assert os.readlink(agents) == replacement.name
    assert not rollback_path.exists()
    assert original_path.is_file()
    assert candidate_path.is_file()
    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )


def test_partial_candidate_artifact_failure_leaves_both_targets_untouched(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    originals = {"AGENTS.md": b"agents\n", "CLAUDE.md": b"claude\n"}
    for name, data in originals.items():
        (git_repo / name).write_bytes(data)
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    state_path = write_ready_state(git_repo, [make_finding()])
    calls = 0
    write_exact_artifact = review_feedback._write_exact_artifact

    def fail_during_artifact_writes(path: Path, data: bytes, mode: int):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected artifact write failure")
        return write_exact_artifact(path, data, mode)

    monkeypatch.setattr(
        review_feedback, "_write_exact_artifact", fail_during_artifact_writes
    )

    with pytest.raises(OSError, match="injected artifact write failure"):
        review_feedback.persist_feedback(state_path)

    for name, original in originals.items():
        assert (git_repo / name).read_bytes() == original
        assert not list(git_repo.glob(f".{name}.feature-review-cycle-1.*"))


def test_foreign_candidate_without_original_fails_without_deleting_or_replacing_it(
    git_repo: Path,
):
    state_path = write_ready_state(
        git_repo,
        [make_finding(disposition="사용자 수용")],
        cycle_id="foreign-candidate",
    )
    target = git_repo / "AGENTS.md"
    candidate = review_feedback._artifact_path(target, "foreign-candidate", "candidate")
    original = review_feedback._artifact_path(target, "foreign-candidate", "original")
    foreign_bytes = b"foreign-user-data\n"
    candidate.write_bytes(foreign_bytes)
    candidate.chmod(0o600)
    foreign_mode = file_mode(candidate)

    with pytest.raises(
        review_feedback.PersistenceError, match="candidate artifact conflicts"
    ):
        review_feedback.persist_feedback(state_path)

    assert candidate.read_bytes() == foreign_bytes
    assert file_mode(candidate) == foreign_mode
    assert not original.exists()
    assert not target.exists()
    assert not (git_repo / "CLAUDE.md").exists()
    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )


def test_no_findings_with_transaction_artifact_fails_closed_without_deleting_it(
    git_repo: Path,
):
    state_path = write_ready_state(git_repo, [], cycle_id="empty-artifact")
    target = git_repo / "AGENTS.md"
    candidate = review_feedback._artifact_path(target, "empty-artifact", "candidate")
    candidate.write_bytes(b"unowned transaction data\n")
    candidate.chmod(0o600)

    with pytest.raises(
        review_feedback.PersistenceError,
        match="artifacts exist without persistable findings",
    ):
        review_feedback.persist_feedback(state_path)

    assert candidate.read_bytes() == b"unowned transaction data\n"
    assert file_mode(candidate) == 0o600
    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )


@pytest.mark.parametrize("target_type", ("symlink", "directory"))
def test_symlink_and_nonregular_targets_are_rejected(git_repo: Path, target_type: str):
    (git_repo / "CLAUDE.md").write_text("claude\n", encoding="utf-8")
    if target_type == "symlink":
        (git_repo / "real-agents.txt").write_text("real\n", encoding="utf-8")
        (git_repo / "AGENTS.md").symlink_to("real-agents.txt")
        run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md", "real-agents.txt")
    else:
        (git_repo / "AGENTS.md").mkdir()
        run_git(git_repo, "add", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add unusual target")
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state_dir = git_state_dir(git_repo)
    review_feedback.create_state_dir(state_dir, state)
    state = complete_round(state, snapshot, state_dir)
    state["findings"] = [make_finding(disposition="제안됨", severity="suggestion")]

    with pytest.raises(review_feedback.StateError, match="not a regular file"):
        review_feedback.finalize_for_persistence(state, snapshot)

    assert state["status"] == "active"


def test_identical_candidates_are_verified_noops(git_repo: Path):
    finding = make_finding()
    for name in review_feedback.TARGET_NAMES:
        candidate = review_feedback.build_guidance_candidate("", [finding], name)
        (git_repo / name).write_text(candidate, encoding="utf-8")
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "preexisting feedback")
    state_path = write_ready_state(git_repo, [finding])

    result = review_feedback.persist_feedback(state_path)

    assert result["changed"] is False
    assert all(not target["changed"] for target in result["targets"].values())


def test_cli_state_commands_drive_full_review_lifecycle(git_repo: Path):
    scope = {"task": "CLI lifecycle smoke"}

    def run_cli(*args: str) -> dict:
        command = list(args)
        if command[0] in {"state", "persist"} and "--cycle-id" not in command:
            command.extend(("--cycle-id", "cli-lifecycle"))
        completed = subprocess.run(
            [sys.executable, str(HELPER_PATH), *command],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    initialized = run_cli(
        "init",
        "--repo",
        str(git_repo),
        "--scope-json",
        json.dumps(scope, ensure_ascii=False),
        "--cycle-id",
        "cli-lifecycle",
    )
    state_path = Path(initialized["state_file"])
    assert state_path == git_state_dir(git_repo) / review_feedback.STATE_FILE
    assert file_mode(state_path) == 0o600
    assert initialized["pending_action"] == "launch-round"

    resumed = run_cli(
        "resume",
        "--state",
        str(state_path),
        "--cycle-id",
        "cli-lifecycle",
        "--scope-json",
        json.dumps(scope, ensure_ascii=False),
    )
    assert resumed["action"] == "launch-round"

    begun = run_cli(
        "state",
        "--state",
        str(state_path),
        "--action",
        "begin-round",
    )
    assert begun["round"] == 1
    assert begun["pending_action"] == "run-reviewers"

    reserved = run_cli(
        "state",
        "--state",
        str(state_path),
        "--action",
        "reserve-launches",
        "--payload-json",
        json.dumps(list(review_feedback.REVIEWER_SLOTS)),
    )
    assert reserved["launching_slots"] == list(review_feedback.REVIEWER_SLOTS)

    for slot in review_feedback.REVIEWER_SLOTS:
        run_cli(
            "state",
            "--state",
            str(state_path),
            "--action",
            "slot-running",
            "--slot",
            slot,
            "--job-id",
            f"job-{slot}",
            "--attempt",
            "1",
        )
        output = state_path.parent / "round-1" / f"{slot}.md"
        output.write_text(f"{slot} CLI review output\n", encoding="utf-8")
        run_cli(
            "state",
            "--state",
            str(state_path),
            "--action",
            "slot-success",
            "--slot",
            slot,
            "--attempt",
            "1",
        )

    reviewed = run_cli(
        "state",
        "--state",
        str(state_path),
        "--action",
        "round-reviewed",
    )
    assert reviewed["phase"] == "consolidation"
    assert reviewed["pending_action"] == "consolidate-round"

    finding = make_finding(disposition="open", severity="warning")
    run_cli(
        "state",
        "--state",
        str(state_path),
        "--action",
        "record-gaps",
        "--payload-json",
        "[]",
    )
    run_cli(
        "state",
        "--state",
        str(state_path),
        "--action",
        "record-findings",
        "--payload-json",
        json.dumps([finding], ensure_ascii=False),
    )
    consolidated = run_cli(
        "state",
        "--state",
        str(state_path),
        "--action",
        "consolidate-round",
    )
    assert consolidated["phase"] == "decision"
    assert consolidated["pending_action"] == "await-user-decision"
    awaited = run_cli(
        "state",
        "--state",
        str(state_path),
        "--action",
        "await-user",
    )
    assert awaited["pending_action"] == "await-user-decision"

    run_cli(
        "state",
        "--state",
        str(state_path),
        "--action",
        "apply-decisions",
        "--payload-json",
        json.dumps({finding["id"]: "사용자 수용"}, ensure_ascii=False),
    )
    decided_state = review_feedback.read_state(state_path)
    assert decided_state["findings"][0]["disposition"] == "사용자 수용"

    finalized = run_cli(
        "state",
        "--state",
        str(state_path),
        "--action",
        "finalize",
    )
    assert finalized["status"] == "terminal-pending-persistence"
    assert finalized["pending_action"] == "persist-feedback"

    persisted = run_cli("persist", "--state", str(state_path))
    assert persisted["changed"] is True
    completed_state = review_feedback.read_state(state_path)
    assert completed_state["status"] == "complete"
    for name in review_feedback.TARGET_NAMES:
        assert (git_repo / name).read_text(encoding="utf-8").count(
            f"feature:codex-review-id:{finding['id']};"
        ) == 1


def test_state_and_persist_cli_reject_stale_cycle_id_without_mutation(
    git_repo: Path,
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="current-cycle"
    )
    state_dir = git_state_dir(git_repo)
    state_path = review_feedback.create_state_dir(state_dir, state)
    stale_state_args = review_feedback._build_parser().parse_args(
        [
            "state",
            "--state",
            str(state_path),
            "--cycle-id",
            "discarded-cycle",
            "--action",
            "begin-round",
        ]
    )

    with pytest.raises(review_feedback.StateError, match="cycle_id mismatch"):
        review_feedback._cmd_state(stale_state_args)
    assert review_feedback.read_state(state_path) == state
    assert not (state_dir / "round-1").exists()

    finding = make_finding(disposition="open", severity="warning")
    ready = complete_round(state, snapshot, state_dir, findings=[finding])
    ready = review_feedback.apply_user_decisions(ready, {finding["id"]: "사용자 수용"})
    ready = review_feedback.finalize_for_persistence(ready, snapshot)
    review_feedback.atomic_write_json(state_path, ready)

    stale_persist = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "persist",
            "--state",
            str(state_path),
            "--cycle-id",
            "discarded-cycle",
        ],
        capture_output=True,
        text=True,
    )

    assert stale_persist.returncode == 1
    assert "cycle_id mismatch" in stale_persist.stderr
    assert review_feedback.read_state(state_path) == ready
    assert not (git_repo / "AGENTS.md").exists()
    assert not (git_repo / "CLAUDE.md").exists()


def test_cli_persist_happy_path_completes_state(git_repo: Path):
    state_path = write_ready_state(git_repo, [make_finding()], cycle_id="cli-cycle")

    completed = run_persist_cli(state_path)
    completed.check_returncode()
    result = json.loads(completed.stdout)
    state = review_feedback.read_state(state_path)

    assert result["cycle_id"] == "cli-cycle"
    assert result["changed"] is True
    assert state["status"] == "complete"
    assert state["phase"] == "complete"
    assert state["pending_action"] == "none"


def test_cli_rerun_completes_terminal_state_after_verified_process_crash(
    git_repo: Path,
):
    state_path = write_ready_state(git_repo, [make_finding()], cycle_id="rerun-cycle")
    crashed = crash_persist_at(state_path, "verified", 73)

    assert crashed.returncode == 73, crashed.stderr
    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )

    completed = run_persist_cli(state_path)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["changed"] is False
    assert review_feedback.read_state(state_path)["status"] == "complete"
    for name in review_feedback.TARGET_NAMES:
        assert not list(git_repo.glob(f".{name}.feature-review-rerun-cycle.*"))


def test_cli_rerun_cleans_artifacts_after_complete_state_process_crash(
    git_repo: Path,
):
    state_path = write_ready_state(
        git_repo, [make_finding()], cycle_id="complete-crash-cycle"
    )
    crashed = crash_persist_at(state_path, "state-complete", 75)

    assert crashed.returncode == 75, crashed.stderr
    complete = review_feedback.read_state(state_path)
    assert complete["status"] == "complete"
    assert (
        review_feedback.resume_action(
            complete,
            cycle_id=complete["cycle_id"],
            repo_root=git_repo,
            scope_identity=complete["initial_scope"],
        )
        == "persist-feedback"
    )

    completed = run_persist_cli(state_path)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["changed"] is False
    for name in review_feedback.TARGET_NAMES:
        assert not list(git_repo.glob(f".{name}.feature-review-complete-crash-cycle.*"))


def test_complete_recovery_conflict_preserves_committed_guidance_and_artifacts(
    git_repo: Path,
):
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id="complete-conflict-cycle",
    )
    crashed = crash_persist_at(state_path, "state-complete", 76)
    assert crashed.returncode == 76, crashed.stderr

    state = review_feedback.read_state(state_path)
    assert state["status"] == "complete"
    agents = git_repo / "AGENTS.md"
    claude = git_repo / "CLAUDE.md"
    agents_candidate = review_feedback._artifact_path(
        agents, state["cycle_id"], "candidate"
    )
    claude_candidate = review_feedback._artifact_path(
        claude, state["cycle_id"], "candidate"
    )
    expected_agents = agents.read_bytes()
    expected_claude = claude.read_bytes()

    def remove_committed_target(event: str, _context: dict) -> None:
        if event == "candidates-ready":
            agents.unlink()

    with pytest.raises(
        review_feedback.PersistenceError,
        match="final verification failed",
    ):
        review_feedback.persist_feedback(state_path, hook=remove_committed_target)

    assert review_feedback.read_state(state_path)["status"] == "complete"
    assert not agents.exists()
    assert claude.read_bytes() == expected_claude
    assert agents_candidate.read_bytes() == expected_agents
    assert claude_candidate.read_bytes() == expected_claude

    os.link(agents_candidate, agents)
    result = review_feedback.persist_feedback(state_path)

    assert result["changed"] is False
    assert agents.read_bytes() == expected_agents
    assert claude.read_bytes() == expected_claude
    for name in review_feedback.TARGET_NAMES:
        target = git_repo / name
        assert not review_feedback._artifact_path(
            target, state["cycle_id"], "candidate"
        ).exists()
        assert not review_feedback._artifact_path(
            target, state["cycle_id"], "original"
        ).exists()


def test_state_commit_then_interrupt_never_rolls_back_persisted_guidance(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id="commit-interrupt-cycle",
    )
    real_atomic_write = review_feedback.atomic_write_json

    def commit_then_interrupt(path: Path, value: dict) -> None:
        real_atomic_write(path, value)
        if value.get("status") == "complete":
            raise KeyboardInterrupt("injected post-commit interrupt")

    monkeypatch.setattr(review_feedback, "atomic_write_json", commit_then_interrupt)
    with pytest.raises(
        review_feedback.PersistenceError,
        match="completed persistence recovery failed",
    ):
        review_feedback.persist_feedback(state_path)

    state = review_feedback.read_state(state_path)
    assert state["status"] == "complete"
    for name in review_feedback.TARGET_NAMES:
        target = git_repo / name
        assert target.is_file()
        assert f"feature:codex-review-id:{make_finding()['id']};" in target.read_text(
            encoding="utf-8"
        )
        assert review_feedback._artifact_path(
            target, state["cycle_id"], "candidate"
        ).is_file()

    monkeypatch.setattr(review_feedback, "atomic_write_json", real_atomic_write)
    assert review_feedback.persist_feedback(state_path)["changed"] is False


def test_unknown_state_commit_outcome_preserves_guidance_and_artifacts(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id="unknown-commit-outcome",
    )
    real_atomic_write = review_feedback.atomic_write_json
    real_read_state = review_feedback.read_state
    transient_reads = 0

    def commit_then_fail(path: Path, value: dict) -> None:
        nonlocal transient_reads
        real_atomic_write(path, value)
        if value.get("status") == "complete":
            transient_reads = 2
            raise OSError("injected post-commit failure")

    def transient_read(path: Path) -> dict:
        nonlocal transient_reads
        if transient_reads:
            transient_reads -= 1
            raise review_feedback.StateError("injected transient read failure")
        return real_read_state(path)

    monkeypatch.setattr(review_feedback, "atomic_write_json", commit_then_fail)
    monkeypatch.setattr(review_feedback, "read_state", transient_read)
    with pytest.raises(
        review_feedback.PersistenceError,
        match="commit outcome is unknown.*artifacts preserved",
    ):
        review_feedback.persist_feedback(state_path)

    state = real_read_state(state_path)
    assert state["status"] == "complete"
    for name in review_feedback.TARGET_NAMES:
        target = git_repo / name
        assert target.is_file()
        assert review_feedback._artifact_path(
            target, state["cycle_id"], "candidate"
        ).is_file()

    monkeypatch.setattr(review_feedback, "atomic_write_json", real_atomic_write)
    monkeypatch.setattr(review_feedback, "read_state", real_read_state)
    assert review_feedback.persist_feedback(state_path)["changed"] is False


def test_cli_recovers_when_only_first_candidate_survived_a_process_crash(
    git_repo: Path,
):
    state_path = write_ready_state(git_repo, [make_finding()], cycle_id="partial-cycle")
    crashed = crash_persist_at(state_path, "after-replace:AGENTS.md", 74)

    assert crashed.returncode == 74, crashed.stderr
    assert (git_repo / "AGENTS.md").is_file()
    assert not (git_repo / "CLAUDE.md").exists()
    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )

    completed = run_persist_cli(state_path)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["targets"]["AGENTS.md"]["changed"] is False
    assert result["targets"]["CLAUDE.md"]["changed"] is True
    assert review_feedback.read_state(state_path)["status"] == "complete"
    for name in review_feedback.TARGET_NAMES:
        assert not list(git_repo.glob(f".{name}.feature-review-partial-cycle.*"))


def test_crash_recovery_does_not_overwrite_a_concurrently_deleted_target(
    git_repo: Path,
):
    originals = {
        "AGENTS.md": b"agents original\n",
        "CLAUDE.md": b"claude original\n",
    }
    for name, data in originals.items():
        (git_repo / name).write_bytes(data)
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    state_path = write_ready_state(
        git_repo,
        [make_finding()],
        cycle_id="recovery-delete-cycle",
    )
    crashed = crash_persist_at(state_path, "before-publish:AGENTS.md", 77)
    assert crashed.returncode == 77, crashed.stderr
    assert not (git_repo / "AGENTS.md").exists()

    def delete_recovered_target(event: str, _context: dict) -> None:
        if event == "verified":
            (git_repo / "AGENTS.md").unlink()

    with pytest.raises(
        review_feedback.PersistenceError,
        match="partial rollback.*target disappeared after publish",
    ):
        review_feedback.persist_feedback(state_path, hook=delete_recovered_target)

    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )
    assert not (git_repo / "AGENTS.md").exists()
    assert (git_repo / "CLAUDE.md").read_bytes() == originals["CLAUDE.md"]
    agents = git_repo / "AGENTS.md"
    assert review_feedback._artifact_path(
        agents, "recovery-delete-cycle", "candidate"
    ).is_file()
    assert (
        review_feedback._artifact_path(
            agents, "recovery-delete-cycle", "original"
        ).read_bytes()
        == originals["AGENTS.md"]
    )


def test_dedupe_cannot_downgrade_open_critical_blocker_to_suggestion(
    git_repo: Path, tmp_path: Path
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state = complete_round(state, snapshot, tmp_path / "cycle")
    critical = make_finding("same-root", disposition="open", severity="critical")
    suggestion = make_finding("same-root", disposition="제안됨", severity="suggestion")
    suggestion["source_rounds"] = [2]
    state["findings"] = [critical, suggestion]

    with pytest.raises(
        review_feedback.StateError,
        match="blocking findings cannot finish as suggestions",
    ):
        review_feedback.finalize_for_persistence(state, snapshot)


def test_prepare_rereview_approves_current_paths_without_incrementing_round(
    git_repo: Path, tmp_path: Path
):
    (git_repo / "tracked.txt").write_text("reviewed\n", encoding="utf-8")
    reviewed = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=reviewed, cycle_id="cycle-a"
    )
    state = complete_round(state, reviewed, tmp_path / "cycle")
    (git_repo / "tracked.txt").write_text("fixed\n", encoding="utf-8")
    (git_repo / "new-approved.py").write_text("new path\n", encoding="utf-8")
    current = review_feedback.capture_repo_snapshot(git_repo)

    prepared = review_feedback.prepare_rereview(state, current)

    assert prepared["phase"] == "re-review"
    assert prepared["pending_action"] == "launch-round"
    assert prepared["round"] == state["round"]
    assert prepared["approved_paths"] == current["paths"]
    assert prepared["reviewed_snapshot"] is None


def test_prepare_rereview_rejects_changed_head(git_repo: Path, tmp_path: Path):
    (git_repo / "tracked.txt").write_text("reviewed\n", encoding="utf-8")
    reviewed = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=reviewed, cycle_id="cycle-a"
    )
    state = complete_round(state, reviewed, tmp_path / "cycle")
    run_git(git_repo, "add", "tracked.txt")
    run_git(git_repo, "commit", "-qm", "mid-cycle commit")
    current = review_feedback.capture_repo_snapshot(git_repo)

    with pytest.raises(review_feedback.StateError, match="HEAD changed"):
        review_feedback.prepare_rereview(state, current)


@pytest.mark.parametrize(
    "transition",
    (
        "mark-round-reviewed",
        "set-await-user-decision",
        "finalize-for-persistence",
        "prepare-rereview",
    ),
)
def test_aborted_state_cannot_be_revived_by_later_transitions(
    git_repo: Path, tmp_path: Path, transition: str
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    cycle_dir = tmp_path / "cycle"
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state = complete_round(state, snapshot, cycle_dir)
    state["findings"] = [make_finding()]
    aborted = review_feedback.abort_state(state, "사용자가 리뷰를 중단했습니다.")
    before = deepcopy(aborted)

    with pytest.raises(review_feedback.StateError):
        if transition == "mark-round-reviewed":
            review_feedback.mark_round_reviewed(aborted, snapshot, cycle_dir=cycle_dir)
        elif transition == "set-await-user-decision":
            review_feedback.set_await_user_decision(aborted)
        elif transition == "finalize-for-persistence":
            review_feedback.finalize_for_persistence(aborted, snapshot)
        else:
            review_feedback.prepare_rereview(aborted, snapshot)

    assert aborted == before


def test_succeeded_slot_records_safe_current_round_output_and_digest(
    git_repo: Path, tmp_path: Path
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state = review_feedback.begin_round(state, snapshot)
    state = start_slot(state, "bugs", job_id="job-1")
    state_dir = tmp_path / "state"
    output = state_dir / "round-1" / "bugs.md"
    output.parent.mkdir(parents=True)
    output.write_text("review finding\n", encoding="utf-8")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()

    completed = review_feedback.mark_slot_result(
        state,
        "bugs",
        succeeded=True,
        output_path="round-1/bugs.md",
        attempt=state["reviewer_slots"]["bugs"]["attempt"],
        output_digest=digest,
        state_dir=state_dir,
    )

    record = completed["reviewer_slots"]["bugs"]
    assert record["status"] == "completed"
    assert record["output_path"] == "round-1/bugs.md"
    assert record["output_digest"] == digest


@pytest.mark.parametrize(
    ("output_path", "contents"),
    (
        ("../escape.md", b"escape\n"),
        ("round-2/bugs.md", b"wrong round\n"),
        ("round-1/bugs.md", b"nonempty but wrong digest\n"),
        ("round-1/bugs.md", b""),
        ("round-1/missing.md", None),
    ),
)
def test_succeeded_slot_rejects_unsafe_missing_empty_or_wrong_round_output(
    git_repo: Path,
    tmp_path: Path,
    output_path: str,
    contents: bytes | None,
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state = review_feedback.begin_round(state, snapshot)
    state = start_slot(state, "bugs", job_id="job-1")
    state_dir = tmp_path / "state"
    resolved = state_dir / output_path
    if contents is not None and ".." not in Path(output_path).parts:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(contents)

    with pytest.raises(review_feedback.StateError):
        review_feedback.mark_slot_result(
            state,
            "bugs",
            succeeded=True,
            output_path=output_path,
            attempt=state["reviewer_slots"]["bugs"]["attempt"],
            output_digest="0" * 64,
            state_dir=state_dir,
        )


def test_mark_round_reviewed_rejects_output_changed_after_slot_completion(
    git_repo: Path, tmp_path: Path
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state = review_feedback.begin_round(state, snapshot)
    cycle_dir = tmp_path / "cycle"
    round_dir = cycle_dir / "round-1"
    round_dir.mkdir(parents=True)
    for slot in review_feedback.REVIEWER_SLOTS:
        output = round_dir / f"{slot}.md"
        output.write_text(f"{slot} review output\n", encoding="utf-8")
        state = start_slot(state, slot, job_id=f"job-{slot}")
        state = review_feedback.mark_slot_result(
            state,
            slot,
            succeeded=True,
            output_path=f"round-1/{slot}.md",
            attempt=state["reviewer_slots"][slot]["attempt"],
            output_digest=hashlib.sha256(output.read_bytes()).hexdigest(),
            state_dir=cycle_dir,
        )
    (round_dir / "bugs.md").write_text("tampered output\n", encoding="utf-8")

    with pytest.raises(review_feedback.StateError, match="reviewer output changed"):
        review_feedback.mark_round_reviewed(state, snapshot, cycle_dir=cycle_dir)


def test_finalize_requires_decision_phase(git_repo: Path):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state["reviewed_snapshot"] = deepcopy(snapshot)
    state["findings"] = [make_finding()]

    with pytest.raises(review_feedback.StateError):
        review_feedback.finalize_for_persistence(state, snapshot)


def test_finalize_rejects_completed_slots_without_safe_output_digest(git_repo: Path):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="cycle-a"
    )
    state.update(
        round=1,
        phase="decision",
        pending_action="await-user-decision",
        reviewed_snapshot=deepcopy(snapshot),
    )
    state["reviewer_slots"] = {
        slot: {
            "status": "completed",
            "attempt": 1,
            "job_id": f"job-{slot}",
            "output_path": f"round-1/{slot}.md",
            "output_digest": None,
        }
        for slot in review_feedback.REVIEWER_SLOTS
    }
    state["findings"] = [make_finding()]

    with pytest.raises(review_feedback.StateError):
        review_feedback.finalize_for_persistence(state, snapshot)


def test_edit_injected_immediately_before_replace_is_preserved_and_fails(
    git_repo: Path,
):
    agents = git_repo / "AGENTS.md"
    claude = git_repo / "CLAUDE.md"
    agents.write_text("agents original\n", encoding="utf-8")
    claude.write_text("claude original\n", encoding="utf-8")
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    state_path = write_ready_state(git_repo, [make_finding()])

    def concurrent_edit(event: str, _context: dict):
        if event == "before-replace:AGENTS.md":
            agents.write_text("last-moment concurrent edit\n", encoding="utf-8")

    with pytest.raises(review_feedback.PersistenceError, match="target changed"):
        review_feedback.persist_feedback(state_path, hook=concurrent_edit)

    assert agents.read_text(encoding="utf-8") == "last-moment concurrent edit\n"
    assert claude.read_text(encoding="utf-8") == "claude original\n"


def test_deleted_external_anchor_fails_on_later_reference_update():
    finding = make_finding(
        "external-a",
        coverage={
            "AGENTS.md": {
                "kind": "external",
                "anchor": "EXACT EXTERNAL ANCHOR",
                "label": "기존 외부 규칙",
            },
            "CLAUDE.md": {"kind": "managed"},
        },
    )
    first = review_feedback.build_guidance_candidate(
        "# Existing\n\nEXACT EXTERNAL ANCHOR\n",
        [finding],
        "AGENTS.md",
    )
    without_anchor = first.replace("EXACT EXTERNAL ANCHOR\n", "")
    updated = deepcopy(finding)
    updated["review_date"] = "2026-07-21"
    updated["disposition"] = "보류"

    with pytest.raises(
        review_feedback.PersistenceError, match="must occur exactly once"
    ):
        review_feedback.build_guidance_candidate(without_anchor, [updated], "AGENTS.md")


def test_crlf_heading_and_line_endings_are_preserved():
    original = (
        "# Existing\r\n\r\n"
        f"{review_feedback.HEADING}\r\n\r\n"
        f"{review_feedback.START_MARKER}\r\n"
        f"{review_feedback.END_MARKER}\r\n\r\n"
        "tail stays here\r\n"
    )

    candidate = review_feedback.build_guidance_candidate(
        original, [make_finding()], "AGENTS.md"
    )

    assert candidate.count(review_feedback.HEADING) == 1
    assert "\n" not in candidate.replace("\r\n", "")
    assert candidate.startswith("# Existing\r\n\r\n")
    assert candidate.endswith("\r\n\r\ntail stays here\r\n")


def test_submodule_head_and_dirty_content_change_snapshot_fingerprint(
    git_repo: Path, tmp_path: Path
):
    source = tmp_path / "submodule-source"
    source.mkdir()
    run_git(source, "init", "-q")
    run_git(source, "config", "user.name", "Feature Tests")
    run_git(source, "config", "user.email", "feature-tests@example.com")
    (source / "sub.txt").write_text("base\n", encoding="utf-8")
    run_git(source, "add", "sub.txt")
    run_git(source, "commit", "-qm", "submodule initial")
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "-C",
            str(git_repo),
            "submodule",
            "add",
            "-q",
            str(source),
            "vendor/sub",
        ],
        check=True,
    )
    run_git(git_repo, "add", ".gitmodules", "vendor/sub")
    run_git(git_repo, "commit", "-qm", "add submodule")
    checkout = git_repo / "vendor" / "sub"
    run_git(checkout, "config", "user.name", "Feature Tests")
    run_git(checkout, "config", "user.email", "feature-tests@example.com")

    clean = review_feedback.capture_repo_snapshot(git_repo)
    (checkout / "sub.txt").write_text("dirty one\n", encoding="utf-8")
    dirty_one = review_feedback.capture_repo_snapshot(git_repo)
    (checkout / "sub.txt").write_text("dirty two\n", encoding="utf-8")
    dirty_two = review_feedback.capture_repo_snapshot(git_repo)
    run_git(checkout, "add", "sub.txt")
    run_git(checkout, "commit", "-qm", "advance submodule head")
    advanced_head = review_feedback.capture_repo_snapshot(git_repo)

    assert dirty_one["paths"] == ["vendor/sub"]
    assert dirty_two["paths"] == ["vendor/sub"]
    assert advanced_head["paths"] == ["vendor/sub"]
    assert (
        len(
            {
                clean["fingerprint"],
                dirty_one["fingerprint"],
                dirty_two["fingerprint"],
                advanced_head["fingerprint"],
            }
        )
        == 4
    )


@pytest.mark.parametrize("missing_field", ("coverage", "review_date"))
def test_finalize_rejects_incomplete_reusable_learning_before_terminal_transition(
    git_repo: Path, tmp_path: Path, missing_field: str
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="metadata-cycle"
    )
    state = complete_round(state, snapshot, tmp_path / "cycle")
    finding = make_finding(
        disposition="제안됨",
        reusable=True,
        severity="suggestion",
    )
    finding.pop(missing_field)
    state["findings"] = [finding]
    before = deepcopy(state)

    with pytest.raises(review_feedback.ReviewFeedbackError, match="missing"):
        review_feedback.finalize_for_persistence(state, snapshot)

    assert state == before
    assert state["status"] == "active"
    assert state["phase"] == "decision"
    assert state["pending_action"] == "await-user-decision"


@pytest.mark.parametrize("failure_kind", ("metadata", "anchor"))
def test_finalize_preflight_failure_can_reopen_correct_and_reapply_decision(
    git_repo: Path,
    tmp_path: Path,
    failure_kind: str,
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo,
        "scope",
        snapshot=snapshot,
        cycle_id=f"reopen-{failure_kind}",
    )
    finding = make_finding(
        "correctable-finding",
        disposition="open",
        severity="warning",
        coverage={
            "AGENTS.md": {
                "kind": "external",
                "anchor": "MISSING EXTERNAL ANCHOR",
                "label": "수정 전 외부 규칙",
            },
            "CLAUDE.md": {"kind": "managed"},
        }
        if failure_kind == "anchor"
        else None,
    )
    state = complete_round(
        state,
        snapshot,
        tmp_path / "cycle",
        findings=[finding],
    )
    decided = review_feedback.apply_user_decisions(
        state, {finding["id"]: "사용자 수용"}
    )
    broken = deepcopy(decided)
    if failure_kind == "metadata":
        broken["findings"][0].pop("review_date")

    with pytest.raises(review_feedback.StateError, match="preflight"):
        review_feedback.finalize_for_persistence(broken, snapshot)

    reopened = review_feedback.reopen_consolidation(broken)

    assert reopened["status"] == "active"
    assert reopened["phase"] == "consolidation"
    assert reopened["pending_action"] == "consolidate-round"
    assert reopened["round_consolidated"] == reopened["round"] - 1
    assert reopened["round_results"] == {
        "round": reopened["round"],
        "gaps_recorded": False,
        "findings_recorded": False,
    }
    assert reopened["decision_log"] == {}

    corrected = make_finding(
        finding["id"],
        disposition="open",
        severity="warning",
    )
    reopened = review_feedback.record_requirement_gaps(reopened, [])
    reopened = review_feedback.record_verified_findings(reopened, [corrected])
    reconsolidated = review_feedback.consolidate_review_round(reopened)
    with pytest.raises(
        review_feedback.StateError, match="final disposition|provenance"
    ):
        review_feedback.finalize_for_persistence(reconsolidated, snapshot)

    redecided = review_feedback.apply_user_decisions(
        reconsolidated, {finding["id"]: "사용자 수용"}
    )
    terminal = review_feedback.finalize_for_persistence(redecided, snapshot)

    assert terminal["status"] == "terminal-pending-persistence"
    assert terminal["findings"][0]["coverage"] == corrected["coverage"]
    assert terminal["decision_log"][finding["id"]] == {
        "disposition": "사용자 수용",
        "round": terminal["round"],
    }


@pytest.mark.parametrize("severity", ("warning", "critical"))
def test_resolved_blocker_requires_a_later_completed_full_review_round(
    git_repo: Path, tmp_path: Path, severity: str
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    cycle_dir = tmp_path / "cycle"
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id=f"{severity}-cycle"
    )
    finding = make_finding(disposition="open", severity=severity)
    state = complete_round(state, snapshot, cycle_dir, findings=[finding])
    before = deepcopy(state)

    with pytest.raises(review_feedback.StateError):
        review_feedback.apply_user_decisions(state, {finding["id"]: "해결됨"})

    assert state == before
    state = review_feedback.prepare_rereview(state, snapshot)
    state = complete_round(state, snapshot, cycle_dir)
    decided = review_feedback.apply_user_decisions(state, {finding["id"]: "해결됨"})

    assert decided["round"] == 2
    assert decided["findings"][0]["disposition"] == "해결됨"


def test_all_waived_later_round_cannot_prove_a_blocker_was_resolved(
    git_repo: Path, tmp_path: Path
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    cycle_dir = tmp_path / "cycle"
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="waived-rereview"
    )
    blocker = make_finding(
        "waived-blocker",
        disposition="open",
        severity="warning",
        reusable=False,
    )
    state = complete_round(
        state,
        snapshot,
        cycle_dir,
        findings=[blocker],
    )
    state = review_feedback.prepare_rereview(state, snapshot)
    state = review_feedback.begin_round(state, snapshot)
    for slot in review_feedback.REVIEWER_SLOTS:
        for attempt in (1, 2):
            state = start_slot(state, slot, job_id=f"job-{slot}-{attempt}")
            state = review_feedback.mark_slot_result(
                state,
                slot,
                succeeded=False,
                output_path=None,
                attempt=state["reviewer_slots"][slot]["attempt"],
            )
        state = review_feedback.set_await_reviewer_decision(state, slot)
        state = review_feedback.waive_slot(
            state,
            slot,
            reason=f"사용자가 {slot} 관점 누락을 승인했습니다.",
        )

    try:
        reviewed = review_feedback.mark_round_reviewed(
            state, snapshot, cycle_dir=cycle_dir
        )
    except review_feedback.StateError as exc:
        assert "waiv" in str(exc).lower() or "completed" in str(exc).lower()
    else:
        reviewed = review_feedback.record_requirement_gaps(reviewed, [])
        reviewed = review_feedback.record_verified_findings(reviewed, [])
        consolidated = review_feedback.consolidate_review_round(reviewed)
        with pytest.raises(
            review_feedback.StateError,
            match="later completed full review|completed reviewer|waiv",
        ):
            review_feedback.apply_user_decisions(
                consolidated, {blocker["id"]: "해결됨"}
            )


def test_prior_full_rereview_still_proves_resolution_after_a_waived_round(
    git_repo: Path, tmp_path: Path
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    cycle_dir = tmp_path / "cycle"
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="prior-full-rereview"
    )
    blocker = make_finding(
        "resolved-before-waiver",
        disposition="open",
        severity="warning",
        reusable=False,
    )
    state = complete_round(state, snapshot, cycle_dir, findings=[blocker])
    state = review_feedback.prepare_rereview(state, snapshot)
    state = complete_round(state, snapshot, cycle_dir)
    assert state["full_review_rounds"] == [1, 2]

    state = review_feedback.prepare_rereview(state, snapshot)
    state = review_feedback.begin_round(state, snapshot)
    for slot in review_feedback.REVIEWER_SLOTS:
        for attempt in (1, 2):
            state = start_slot(state, slot, job_id=f"job-{slot}-{attempt}")
            state = review_feedback.mark_slot_result(
                state,
                slot,
                succeeded=False,
                output_path=None,
                attempt=state["reviewer_slots"][slot]["attempt"],
            )
        state = review_feedback.set_await_reviewer_decision(state, slot)
        state = review_feedback.waive_slot(
            state,
            slot,
            reason=f"사용자가 {slot} 관점 누락을 승인했습니다.",
        )
    state = review_feedback.mark_round_reviewed(state, snapshot, cycle_dir=cycle_dir)
    state = review_feedback.record_requirement_gaps(state, [])
    state = review_feedback.record_verified_findings(state, [])
    state = review_feedback.consolidate_review_round(state)

    assert state["full_review_rounds"] == [1, 2]
    decided = review_feedback.apply_user_decisions(state, {blocker["id"]: "해결됨"})
    assert decided["findings"][0]["disposition"] == "해결됨"


def test_complete_resume_requires_recoverable_transaction_artifacts(git_repo: Path):
    scope = {"task": "complete recovery"}
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, scope, snapshot=snapshot, cycle_id="complete-recovery"
    )
    state_dir = git_state_dir(git_repo)
    state_path = review_feedback.create_state_dir(state_dir, state)
    finding = make_finding(disposition="open")
    state = complete_round(state, snapshot, state_dir, findings=[finding])
    state = review_feedback.apply_user_decisions(state, {finding["id"]: "사용자 수용"})
    state = review_feedback.finalize_for_persistence(state, snapshot)
    review_feedback.atomic_write_json(state_path, state)
    review_feedback.persist_feedback(state_path)
    complete = review_feedback.read_state(state_path)

    with pytest.raises(review_feedback.StateError, match="complete"):
        review_feedback.resume_action(
            complete,
            cycle_id="complete-recovery",
            repo_root=git_repo,
            scope_identity=scope,
        )

    target = git_repo / "AGENTS.md"
    candidate = review_feedback._artifact_path(
        target, complete["cycle_id"], "candidate"
    )
    os.link(target, candidate)

    assert (
        review_feedback.resume_action(
            complete,
            cycle_id="complete-recovery",
            repo_root=git_repo,
            scope_identity=scope,
        )
        == "persist-feedback"
    )


def test_begin_round_state_write_failure_removes_directory_and_allows_retry(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="round-write-failure"
    )
    state_dir = git_state_dir(git_repo)
    state_path = review_feedback.create_state_dir(state_dir, state)
    args = review_feedback._build_parser().parse_args(
        [
            "state",
            "--state",
            str(state_path),
            "--cycle-id",
            state["cycle_id"],
            "--action",
            "begin-round",
        ]
    )
    real_atomic_write = review_feedback.atomic_write_json

    def fail_state_write(path: Path, value: dict) -> None:
        del path, value
        raise OSError("injected state write failure")

    monkeypatch.setattr(review_feedback, "atomic_write_json", fail_state_write)
    with pytest.raises(OSError, match="injected state write failure"):
        review_feedback._cmd_state(args)

    assert review_feedback.read_state(state_path)["round"] == 0
    assert not (state_dir / "round-1").exists()

    monkeypatch.setattr(review_feedback, "atomic_write_json", real_atomic_write)
    assert review_feedback._cmd_state(args) == 0
    assert review_feedback.read_state(state_path)["round"] == 1
    assert (state_dir / "round-1").is_dir()


def test_begin_round_retains_directory_when_state_replace_committed_then_raised(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="round-committed-error"
    )
    state_dir = git_state_dir(git_repo)
    state_path = review_feedback.create_state_dir(state_dir, state)
    args = review_feedback._build_parser().parse_args(
        [
            "state",
            "--state",
            str(state_path),
            "--cycle-id",
            state["cycle_id"],
            "--action",
            "begin-round",
        ]
    )
    real_atomic_write = review_feedback.atomic_write_json

    def commit_then_fail(path: Path, value: dict) -> None:
        real_atomic_write(path, value)
        raise OSError("injected post-replace durability failure")

    monkeypatch.setattr(review_feedback, "atomic_write_json", commit_then_fail)
    with pytest.raises(OSError, match="post-replace durability failure"):
        review_feedback._cmd_state(args)

    committed = review_feedback.read_state(state_path)
    assert committed["round"] == 1
    assert committed["pending_action"] == "run-reviewers"
    assert (state_dir / "round-1").is_dir()
    assert (
        review_feedback.resume_action(
            committed,
            cycle_id=committed["cycle_id"],
            repo_root=git_repo,
            scope_identity=committed["initial_scope"],
        )
        == "run-reviewers"
    )


def test_begin_round_unknown_commit_outcome_preserves_round_directory(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="round-unknown-commit"
    )
    state_dir = git_state_dir(git_repo)
    state_path = review_feedback.create_state_dir(state_dir, state)
    args = review_feedback._build_parser().parse_args(
        [
            "state",
            "--state",
            str(state_path),
            "--cycle-id",
            state["cycle_id"],
            "--action",
            "begin-round",
        ]
    )
    real_atomic_write = review_feedback.atomic_write_json
    real_read_state = review_feedback.read_state
    fail_observer = False

    def commit_then_fail(path: Path, value: dict) -> None:
        nonlocal fail_observer
        real_atomic_write(path, value)
        fail_observer = True
        raise OSError("injected post-commit failure")

    def transient_read(path: Path) -> dict:
        nonlocal fail_observer
        if fail_observer:
            fail_observer = False
            raise review_feedback.StateError("injected transient read failure")
        return real_read_state(path)

    monkeypatch.setattr(review_feedback, "atomic_write_json", commit_then_fail)
    monkeypatch.setattr(review_feedback, "read_state", transient_read)
    with pytest.raises(OSError, match="post-commit failure"):
        review_feedback._cmd_state(args)

    committed = real_read_state(state_path)
    assert committed["round"] == 1
    assert committed["pending_action"] == "run-reviewers"
    assert (state_dir / "round-1").is_dir()


def test_begin_round_reuses_empty_orphan_directory_from_interrupted_transition(
    git_repo: Path,
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="orphan-round"
    )
    state_dir = git_state_dir(git_repo)
    state_path = review_feedback.create_state_dir(state_dir, state)
    orphan = state_dir / "round-1"
    orphan.mkdir(mode=0o700)
    args = review_feedback._build_parser().parse_args(
        [
            "state",
            "--state",
            str(state_path),
            "--cycle-id",
            state["cycle_id"],
            "--action",
            "begin-round",
        ]
    )

    assert review_feedback._cmd_state(args) == 0
    assert review_feedback.read_state(state_path)["round"] == 1
    assert orphan.is_dir()
    assert not any(orphan.iterdir())


def test_complete_persist_rejects_unowned_original_only_artifact(git_repo: Path):
    state_path = write_ready_state(
        git_repo,
        [make_finding(disposition="사용자 수용")],
        cycle_id="original-cleanup",
    )
    review_feedback.persist_feedback(state_path)
    complete = review_feedback.read_state(state_path)
    target = git_repo / "AGENTS.md"
    target.unlink()
    original_path = review_feedback._artifact_path(
        target, complete["cycle_id"], "original"
    )
    original_data = b"unowned original-only data\n"
    original_mode = 0o600
    original_path.write_bytes(original_data)
    original_path.chmod(original_mode)

    with pytest.raises(
        review_feedback.PersistenceError,
        match="original artifact lacks its matching candidate",
    ):
        review_feedback.persist_feedback(state_path)

    assert not target.exists()
    assert original_path.read_bytes() == original_data
    assert file_mode(original_path) == original_mode
    assert complete == review_feedback.read_state(state_path)
    assert (git_repo / "CLAUDE.md").is_file()


def test_replace_that_moves_then_raises_is_rolled_back_and_retryable(git_repo: Path):
    originals = {"AGENTS.md": b"agents original\n", "CLAUDE.md": b"claude original\n"}
    for name, data in originals.items():
        (git_repo / name).write_bytes(data)
    run_git(git_repo, "add", "AGENTS.md", "CLAUDE.md")
    run_git(git_repo, "commit", "-qm", "add guidance")
    state_path = write_ready_state(
        git_repo,
        [make_finding(disposition="사용자 수용")],
        cycle_id="move-then-error",
    )

    def move_then_raise(source: Path, target: Path) -> None:
        os.replace(source, target)
        raise OSError("injected error after move")

    with pytest.raises(review_feedback.PersistenceError, match="rolled back"):
        review_feedback.persist_feedback(state_path, replace=move_then_raise)

    assert review_feedback.read_state(state_path)["status"] == (
        "terminal-pending-persistence"
    )
    for name, data in originals.items():
        assert (git_repo / name).read_bytes() == data
        assert not list(git_repo.glob(f".{name}.feature-review-move-then-error.*"))

    assert review_feedback.persist_feedback(state_path)["changed"] is True


def test_finalize_preflight_can_reopen_and_correct_consolidated_coverage(
    git_repo: Path, tmp_path: Path
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    cycle_dir = tmp_path / "cycle"
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="coverage-correction"
    )
    finding = make_finding(
        disposition="제안됨",
        severity="suggestion",
        coverage={
            "AGENTS.md": {
                "kind": "external",
                "anchor": "missing external rule",
                "label": "기존 규칙",
            },
            "CLAUDE.md": {"kind": "managed"},
        },
    )
    state = complete_round(state, snapshot, cycle_dir, findings=[finding])

    with pytest.raises(review_feedback.StateError, match="persistence preflight"):
        review_feedback.finalize_for_persistence(state, snapshot)

    reopened = review_feedback.reopen_consolidation(state)
    assert reopened["pending_action"] == "consolidate-round"
    corrected = deepcopy(finding)
    corrected["coverage"] = {
        "AGENTS.md": {"kind": "managed"},
        "CLAUDE.md": {"kind": "managed"},
    }
    reopened = review_feedback.record_requirement_gaps(reopened, [])
    reopened = review_feedback.record_verified_findings(reopened, [corrected])
    reconsolidated = review_feedback.consolidate_review_round(reopened)

    finalized = review_feedback.finalize_for_persistence(reconsolidated, snapshot)
    assert finalized["status"] == "terminal-pending-persistence"


def test_metadata_amendment_preserves_original_source_round_and_decision(
    git_repo: Path, tmp_path: Path
):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    cycle_dir = tmp_path / "cycle"
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="metadata-amendment"
    )
    finding = make_finding(
        "metadata-blocker",
        disposition="open",
        severity="warning",
        coverage={
            "AGENTS.md": {
                "kind": "external",
                "anchor": "missing external rule",
                "label": "기존 규칙",
            },
            "CLAUDE.md": {"kind": "managed"},
        },
    )
    state = complete_round(state, snapshot, cycle_dir, findings=[finding])
    state = review_feedback.prepare_rereview(state, snapshot)
    state = complete_round(state, snapshot, cycle_dir)
    state = review_feedback.apply_user_decisions(state, {finding["id"]: "해결됨"})
    decision_log = deepcopy(state["decision_log"])

    with pytest.raises(review_feedback.StateError, match="persistence preflight"):
        review_feedback.finalize_for_persistence(state, snapshot)

    amended = review_feedback.amend_finding_metadata(
        state,
        [
            {
                "id": finding["id"],
                "review_date": "2026-07-21",
                "coverage": {
                    "AGENTS.md": {"kind": "managed"},
                    "CLAUDE.md": {"kind": "managed"},
                },
            }
        ],
    )

    assert amended["findings"][0]["source_rounds"] == [1]
    assert amended["decision_log"] == decision_log
    terminal = review_feedback.finalize_for_persistence(amended, snapshot)
    assert terminal["status"] == "terminal-pending-persistence"


def test_guarded_discard_removes_only_exact_aborted_cycle(git_repo: Path):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="discard-cycle"
    )
    state_dir = git_state_dir(git_repo)
    state_path = review_feedback.create_state_dir(state_dir, state)

    with pytest.raises(review_feedback.StateError, match="aborted, complete"):
        review_feedback.discard_cycle(
            state_path,
            cycle_id=state["cycle_id"],
            reason="must not discard active",
        )

    aborted = review_feedback.abort_state(state, "사용자가 중단했습니다.")
    review_feedback.atomic_write_json(state_path, aborted)
    result = review_feedback.discard_cycle(
        state_path,
        cycle_id=state["cycle_id"],
        reason="사용자가 폐기를 승인했습니다.",
    )

    assert result["discarded"] is True
    assert not state_dir.exists()
    assert (git_repo / "tracked.txt").read_text(encoding="utf-8") == "base\n"


def test_abort_rejects_running_reviewer_before_cycle_discard(git_repo: Path):
    snapshot = review_feedback.capture_repo_snapshot(git_repo)
    state = review_feedback.initialize_state(
        git_repo, "scope", snapshot=snapshot, cycle_id="running-abort"
    )
    state = review_feedback.begin_round(state, snapshot)
    state = start_slot(state, "bugs", job_id="live-job")

    with pytest.raises(review_feedback.StateError, match="jobs may be active"):
        review_feedback.abort_state(state, "사용자가 중단했습니다.")


def test_guarded_discard_allows_artifact_free_terminal_pending_cycle(
    git_repo: Path,
):
    state_path = write_ready_state(
        git_repo,
        [make_finding(disposition="사용자 수용")],
        cycle_id="terminal-discard",
    )
    state_dir = state_path.parent
    result = review_feedback.discard_cycle(
        state_path,
        cycle_id="terminal-discard",
        reason="사용자가 피드백 기록 포기를 승인했습니다.",
    )

    assert result["discarded"] is True
    assert not state_dir.exists()
    assert not list(state_dir.parent.glob(f".{state_dir.name}.discard-*"))
