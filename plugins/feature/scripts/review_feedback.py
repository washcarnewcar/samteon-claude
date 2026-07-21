#!/usr/bin/env python3
"""Durable Codex review state and safe AGENTS.md/CLAUDE.md persistence.

The feature skill owns semantic validation of review findings.  This helper
owns the mechanical contracts that are easy to get wrong in prose: lifecycle
dispatch, snapshot drift detection, managed-block validation, and a guarded
two-file replacement with rollback.
"""

from __future__ import annotations

import argparse
import base64
import copy
import ctypes
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Union

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None
    import msvcrt


SCHEMA_VERSION = 5
MODE = "CODEX_MODE"
STATE_FILE = "state.json"
STATE_DIR_NAME = "feature-code-review-state"
HEADING = "## Codex 코드 리뷰에서 배운 규칙"
START_MARKER = "<!-- feature:codex-review-learnings:start -->"
END_MARKER = "<!-- feature:codex-review-learnings:end -->"
TARGET_NAMES = ("AGENTS.md", "CLAUDE.md")
ARTIFACT_KINDS = ("candidate", "original", "rollback")
REVIEWER_SLOTS = ("bugs", "simplicity", "conventions")
FINAL_DISPOSITIONS = {"해결됨", "사용자 수용", "보류", "제안됨"}
BLOCKING_SEVERITIES = {"critical", "warning"}
SEVERITY_RANK = {"suggestion": 1, "warning": 2, "critical": 3}
ENTRY_RE = re.compile(
    r"^(?P<visible>- .+?) "
    r"<!-- feature:codex-review-id:(?P<id>[A-Za-z0-9._-]+);"
    r"kind:(?P<kind>rule|reference);rule:(?P<rule>[0-9a-f]{64});"
    r"anchor:(?P<anchor>-|[A-Za-z0-9_-]+) -->$"
)
VISIBLE_ENTRY_RE = re.compile(
    r"^- \*\*`(?P<scope>[^`\r\n]+)`\*\*: (?P<detail>.+) "
    r"\(Codex 리뷰 (?P<review_date>\d{4}-\d{2}-\d{2}), "
    r"(?P<disposition>해결됨|사용자 수용|보류|제안됨)\)$"
)
LINUX_RENAMEAT2_SYSCALLS = {
    "x86_64": 316,
    "amd64": 316,
    "i386": 353,
    "i686": 353,
    "arm": 382,
    "armv7l": 382,
    "aarch64": 276,
    "arm64": 276,
    "ppc64": 357,
    "ppc64le": 357,
    "s390x": 347,
    "riscv64": 276,
}
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNSAFE_TEXT_RE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?i:\b(?:password|passwd|api[_-]?key|secret|token)\s*[:=]))"
)


class ReviewFeedbackError(RuntimeError):
    """Base error for invalid state or persistence contracts."""


class StateError(ReviewFeedbackError):
    """Review-cycle state is invalid or cannot be resumed safely."""


class PersistenceError(ReviewFeedbackError):
    """Guidance candidates could not be persisted or rolled back safely."""


def _json_clone(value: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(dict(value))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


PathInput = Union[str, os.PathLike[str]]


def _portable_mode(mode: int) -> int:
    """Preserve POSIX modes and Windows' writable/read-only distinction."""

    normalized = stat.S_IMODE(mode)
    if os.name != "nt":
        return normalized
    readable = (
        stat.S_IREAD if normalized & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH) else 0
    )
    writable = (
        stat.S_IWRITE
        if normalized & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        else 0
    )
    return readable | writable


def _canonical_root(path: PathInput) -> str:
    return str(Path(path).resolve())


def _validate_relative_paths(paths: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise StateError(f"invalid repository-relative path: {raw!r}")
        normalized.append(path.as_posix())
    return sorted(set(normalized))


def _run_git(repo_root: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), *args], stderr=subprocess.STDOUT
        )
    except subprocess.CalledProcessError as exc:
        message = exc.output.decode("utf-8", "replace").strip()
        raise StateError(f"git {' '.join(args)} failed: {message}") from exc


def _index_fingerprint(repo_root: Path, *, exclude_guidance: bool = False) -> str:
    diff_args = [
        "diff",
        "--cached",
        "--binary",
        "--no-ext-diff",
        "--ignore-submodules=none",
        "HEAD",
        "--",
    ]
    listing_args = ["ls-files", "--stage", "-v", "-z", "--"]
    if exclude_guidance:
        pathspec = [
            ".",
            ":(top,exclude)AGENTS.md",
            ":(top,exclude)CLAUDE.md",
        ]
        diff_args.extend(pathspec)
        listing_args.extend(pathspec)
    payload = _run_git(repo_root, *diff_args)
    payload += b"\0feature:index-entries\0"
    payload += _run_git(repo_root, *listing_args)
    return _sha256(payload)


def capture_repo_snapshot(repo_root: PathInput) -> dict[str, Any]:
    """Capture HEAD plus every tracked/untracked working-tree change.

    The fingerprint includes path, file type, mode, and content (or deletion),
    so a clean final review cannot be reused after a commit, path expansion, or
    content change.
    """

    root = Path(repo_root).resolve()
    head = _run_git(root, "rev-parse", "HEAD").decode().strip()
    index_fingerprint = _index_fingerprint(root)
    non_guidance_index_fingerprint = _index_fingerprint(root, exclude_guidance=True)
    changed = set(
        item.decode("utf-8", "surrogateescape")
        for item in _run_git(
            root,
            "diff",
            "--name-only",
            "-z",
            "--ignore-submodules=none",
            "HEAD",
            "--",
        ).split(b"\0")
        if item
    )
    changed.update(
        item.decode("utf-8", "surrogateescape")
        for item in _run_git(
            root, "ls-files", "--others", "--exclude-standard", "-z", "--"
        ).split(b"\0")
        if item
    )
    paths = _validate_relative_paths(changed)
    digest = hashlib.sha256()
    digest.update(head.encode())
    digest.update(b"\0")
    digest.update(index_fingerprint.encode())
    digest.update(b"\0")
    entries: dict[str, dict[str, Any]] = {}
    for rel in paths:
        path = root / rel
        try:
            info = path.lstat()
        except FileNotFoundError:
            record: dict[str, Any] = {"type": "deleted"}
        else:
            record = {"mode": _portable_mode(info.st_mode)}
            if stat.S_ISLNK(info.st_mode):
                record.update(
                    type="symlink",
                    digest=_sha256(
                        os.readlink(path).encode("utf-8", "surrogateescape")
                    ),
                )
            elif stat.S_ISREG(info.st_mode):
                record.update(type="file", digest=_sha256(path.read_bytes()))
            elif stat.S_ISDIR(info.st_mode):
                if (path / ".git").exists():
                    nested = capture_repo_snapshot(path)
                    record.update(
                        type="submodule",
                        digest=_sha256(
                            json.dumps(
                                nested,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ),
                    )
                else:
                    record.update(type="directory")
            else:
                record.update(type="other")
        entries[rel] = record
        digest.update(rel.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        )
        digest.update(b"\0")
    return {
        "head": head,
        "index_fingerprint": index_fingerprint,
        "non_guidance_index_fingerprint": non_guidance_index_fingerprint,
        "paths": paths,
        "entries": entries,
        "fingerprint": digest.hexdigest(),
    }


def initialize_state(
    repo_root: PathInput,
    initial_scope: Any,
    *,
    snapshot: Optional[Mapping[str, Any]] = None,
    cycle_id: Optional[str] = None,
) -> dict[str, Any]:
    root = _canonical_root(repo_root)
    current = dict(snapshot or capture_repo_snapshot(root))
    return {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": cycle_id or uuid.uuid4().hex,
        "repo_root": root,
        "initial_head": current["head"],
        "initial_scope": copy.deepcopy(initial_scope),
        "approved_paths": _validate_relative_paths(current["paths"]),
        "mode": MODE,
        "status": "active",
        "phase": "review",
        "pending_action": "launch-round",
        "round": 0,
        "reviewer_slots": {},
        "reviewer_decision_slot": None,
        "requirement_gaps": [],
        "findings": [],
        "decision_log": {},
        "round_results": {
            "round": 0,
            "gaps_recorded": False,
            "findings_recorded": False,
        },
        "round_consolidated": 0,
        "full_review_rounds": [],
        "reviewed_snapshot": None,
    }


def validate_state(state: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "cycle_id",
        "repo_root",
        "initial_head",
        "initial_scope",
        "approved_paths",
        "mode",
        "status",
        "phase",
        "pending_action",
        "round",
        "reviewer_slots",
        "reviewer_decision_slot",
        "requirement_gaps",
        "findings",
        "decision_log",
        "round_results",
        "round_consolidated",
        "full_review_rounds",
        "reviewed_snapshot",
    }
    missing = required.difference(state)
    if missing:
        raise StateError(f"state is missing fields: {sorted(missing)}")
    if state["schema_version"] != SCHEMA_VERSION or state["mode"] != MODE:
        raise StateError("unsupported state schema or review mode")
    if not isinstance(state["cycle_id"], str) or not SAFE_ID_RE.fullmatch(
        state["cycle_id"]
    ):
        raise StateError("invalid cycle_id")
    if not isinstance(state["round"], int) or state["round"] < 0:
        raise StateError("invalid round")
    _validate_relative_paths(state["approved_paths"])
    if not isinstance(state["reviewer_slots"], dict):
        raise StateError("reviewer_slots must be an object")
    if state["reviewer_decision_slot"] not in {None, *REVIEWER_SLOTS}:
        raise StateError("reviewer_decision_slot is invalid")
    if not isinstance(state["requirement_gaps"], list) or not isinstance(
        state["findings"], list
    ):
        raise StateError("requirement_gaps and findings must be arrays")
    if not isinstance(state["decision_log"], dict):
        raise StateError("decision_log must be an object")
    round_results = state["round_results"]
    if (
        not isinstance(round_results, dict)
        or set(round_results) != {"round", "gaps_recorded", "findings_recorded"}
        or type(round_results["round"]) is not int
        or not isinstance(round_results["gaps_recorded"], bool)
        or not isinstance(round_results["findings_recorded"], bool)
    ):
        raise StateError("round_results is invalid")
    if (
        type(state["round_consolidated"]) is not int
        or state["round_consolidated"] < 0
        or state["round_consolidated"] > state["round"]
    ):
        raise StateError("round_consolidated is invalid")
    full_review_rounds = state["full_review_rounds"]
    if (
        not isinstance(full_review_rounds, list)
        or any(
            type(round_number) is not int
            or round_number < 1
            or round_number > state["round"]
            for round_number in full_review_rounds
        )
        or len(set(full_review_rounds)) != len(full_review_rounds)
    ):
        raise StateError("full_review_rounds is invalid")


def resume_action(
    state: Mapping[str, Any],
    *,
    cycle_id: str,
    repo_root: PathInput,
    scope_identity: Any,
) -> str:
    validate_state(state)
    if state["status"] == "aborted":
        raise StateError("cannot automatically resume aborted cycle")
    if state["cycle_id"] != cycle_id:
        raise StateError("cycle_id mismatch")
    if _canonical_root(repo_root) != state["repo_root"]:
        raise StateError("repo_root mismatch")
    if scope_identity != state["initial_scope"]:
        raise StateError("task/scope identity mismatch")
    if state["status"] == "complete":
        root = Path(state["repo_root"])
        artifacts = [
            _artifact_path(root / name, state["cycle_id"], kind)
            for name in TARGET_NAMES
            for kind in ARTIFACT_KINDS
        ]
        if any(_lexists(path) for path in artifacts):
            return "persist-feedback"
        raise StateError("cannot automatically resume complete cycle")
    pending = state["pending_action"]
    if (
        state["status"] == "terminal-pending-persistence"
        or pending == "persist-feedback"
    ):
        return "persist-feedback"
    if any(
        record.get("status") == "launching"
        for record in state["reviewer_slots"].values()
    ):
        return "reconcile-launches"
    dispatch = {
        "launch-round": "launch-round",
        "run-reviewers": "run-reviewers",
        "consolidate-round": "consolidate-round",
        "await-user-decision": "await-user-decision",
        "await-reviewer-decision": "await-reviewer-decision",
        "retry-reviewer": "retry-reviewer",
    }
    try:
        return dispatch[pending]
    except KeyError as exc:
        raise StateError(f"unsupported pending_action: {pending!r}") from exc


def verify_reviewed_snapshot(
    state: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> None:
    validate_state(state)
    if snapshot.get("head") != state["initial_head"]:
        raise StateError("HEAD changed during the review cycle")
    if _validate_relative_paths(snapshot.get("paths", [])) != _validate_relative_paths(
        state["approved_paths"]
    ):
        raise StateError("working-tree path scope drifted")
    reviewed = state.get("reviewed_snapshot")
    if not isinstance(reviewed, dict):
        raise StateError("no completed review snapshot is recorded")
    if snapshot.get("index_fingerprint") != reviewed.get("index_fingerprint"):
        raise StateError("Git index changed after the completed review")
    if reviewed.get("fingerprint") != snapshot.get("fingerprint"):
        raise StateError("working-tree content changed after the completed review")


def verify_persistence_snapshot(
    state: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> None:
    """Allow guidance recovery while rejecting drift everywhere else."""

    validate_state(state)
    reviewed = state.get("reviewed_snapshot")
    if not isinstance(reviewed, dict):
        raise StateError("no completed review snapshot is recorded")
    if snapshot.get("head") != state["initial_head"]:
        raise StateError("HEAD changed during the review cycle")
    if snapshot.get("non_guidance_index_fingerprint") != reviewed.get(
        "non_guidance_index_fingerprint"
    ):
        raise StateError("non-guidance Git index changed after the completed review")
    reviewed_entries = reviewed.get("entries")
    current_entries = snapshot.get("entries")
    if not isinstance(reviewed_entries, dict) or not isinstance(current_entries, dict):
        raise StateError("review snapshot lacks per-path fingerprints")
    excluded = set(TARGET_NAMES)
    for name in TARGET_NAMES:
        for kind in ARTIFACT_KINDS:
            excluded.add(f".{name}.feature-review-{state['cycle_id']}.{kind}")
    reviewed_non_guidance = {
        path: value for path, value in reviewed_entries.items() if path not in excluded
    }
    current_non_guidance = {
        path: value for path, value in current_entries.items() if path not in excluded
    }
    if reviewed_non_guidance != current_non_guidance:
        raise StateError("non-guidance working-tree content changed after review")


def begin_round(
    state: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    validate_state(state)
    if state["status"] != "active" or state["pending_action"] != "launch-round":
        raise StateError("begin_round requires active launch-round state")
    if snapshot.get("head") != state["initial_head"]:
        raise StateError("HEAD changed before review round")
    if _validate_relative_paths(snapshot.get("paths", [])) != _validate_relative_paths(
        state["approved_paths"]
    ):
        raise StateError("unapproved path scope drift before review round")
    updated = _json_clone(state)
    updated["round"] += 1
    updated["phase"] = "review-round"
    updated["pending_action"] = "run-reviewers"
    updated["reviewer_slots"] = {
        slot: {
            "status": "pending",
            "attempt": 0,
            "job_id": None,
            "output_path": None,
            "output_digest": None,
            "waiver_reason": None,
        }
        for slot in REVIEWER_SLOTS
    }
    updated["reviewer_decision_slot"] = None
    updated["round_snapshot"] = copy.deepcopy(dict(snapshot))
    updated["round_results"] = {
        "round": updated["round"],
        "gaps_recorded": False,
        "findings_recorded": False,
    }
    return updated


def prepare_rereview(
    state: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    """Approve the complete post-fix working tree for a full re-review."""

    validate_state(state)
    if state["status"] != "active" or state["pending_action"] != "await-user-decision":
        raise StateError("prepare_rereview requires an active user-decision state")
    if snapshot.get("head") != state["initial_head"]:
        raise StateError("HEAD changed before re-review")
    updated = _json_clone(state)
    updated["approved_paths"] = _validate_relative_paths(snapshot.get("paths", []))
    updated["reviewed_snapshot"] = None
    updated["phase"] = "re-review"
    updated["pending_action"] = "launch-round"
    return updated


def reserve_launches(state: Mapping[str, Any], slots: Sequence[str]) -> dict[str, Any]:
    """Durably reserve reviewer attempts before starting external jobs."""

    validate_state(state)
    if isinstance(slots, (str, bytes)) or not isinstance(slots, Sequence):
        raise StateError("launch reservation requires a slot array")
    selected = list(slots)
    if (
        not selected
        or len(set(selected)) != len(selected)
        or any(slot not in REVIEWER_SLOTS for slot in selected)
    ):
        raise StateError("launch reservation has invalid or duplicate slots")
    normal_start = (
        state["status"] == "active"
        and state["phase"] == "review-round"
        and state["pending_action"] == "run-reviewers"
    )
    retry_slot = state.get("reviewer_decision_slot")
    retry_start = (
        state["status"] == "active"
        and state["phase"] == "review-round"
        and state["pending_action"] == "retry-reviewer"
        and selected == [retry_slot]
    )
    if not (normal_start or retry_start):
        raise StateError("reviewer launches cannot be reserved in current state")
    if any(
        record.get("status") == "launching"
        for record in state["reviewer_slots"].values()
    ):
        raise StateError("existing launching reviewers must be reconciled first")
    updated = _json_clone(state)
    for slot in selected:
        record = updated["reviewer_slots"][slot]
        if record["status"] not in {"pending", "failed"}:
            raise StateError(f"reviewer slot {slot} is already {record['status']}")
        if (
            normal_start
            and record["status"] == "failed"
            and int(record["attempt"]) >= 2
        ):
            raise StateError(
                f"reviewer slot {slot} requires an explicit retry decision after two failures"
            )
        if retry_start and record["status"] != "failed":
            raise StateError("explicit reviewer retry requires a failed slot")
        record.update(
            status="launching",
            attempt=int(record["attempt"]) + 1,
            job_id=None,
            output_path=None,
            output_digest=None,
            waiver_reason=None,
        )
    if retry_start:
        updated["pending_action"] = "run-reviewers"
        updated["reviewer_decision_slot"] = None
    return updated


def mark_slot_running(
    state: Mapping[str, Any], slot: str, *, job_id: str, attempt: int
) -> dict[str, Any]:
    validate_state(state)
    attach_phase = (
        state["phase"] == "review-round" and state["pending_action"] == "run-reviewers"
    ) or (
        state["phase"] == "reviewer-decision"
        and state["pending_action"] == "await-reviewer-decision"
    )
    if state["status"] != "active" or not attach_phase or slot not in REVIEWER_SLOTS:
        raise StateError("reviewer job cannot be attached in current state")
    updated = _json_clone(state)
    record = updated["reviewer_slots"][slot]
    if not isinstance(job_id, str) or not job_id.strip():
        raise StateError("reviewer job_id must be non-empty")
    if record["status"] not in {"launching", "running"}:
        raise StateError(f"reviewer slot {slot} is not launch-reserved")
    expected_attempt = int(record["attempt"])
    if type(attempt) is not int or attempt != expected_attempt:
        raise StateError(f"stale reviewer attempt for slot {slot}")
    if record["status"] == "running":
        if record.get("job_id") == job_id:
            return updated
        raise StateError(f"reviewer slot {slot} already has another job")
    record.update(
        status="running",
        job_id=job_id,
        output_path=None,
        output_digest=None,
        waiver_reason=None,
    )
    return updated


def set_await_reviewer_decision(state: Mapping[str, Any], slot: str) -> dict[str, Any]:
    validate_state(state)
    record = state["reviewer_slots"].get(slot, {})
    already_waiting = (
        state["status"] == "active"
        and state["phase"] == "reviewer-decision"
        and state["pending_action"] == "await-reviewer-decision"
        and state["reviewer_decision_slot"] == slot
        and record.get("status") == "failed"
        and int(record.get("attempt", 0)) >= 2
    )
    if already_waiting:
        return _json_clone(state)
    if (
        state["status"] != "active"
        or state["phase"] != "review-round"
        or state["pending_action"] != "run-reviewers"
        or slot not in REVIEWER_SLOTS
        or record.get("status") != "failed"
        or int(record.get("attempt", 0)) < 2
    ):
        raise StateError("reviewer decision wait requires a twice-failed slot")
    updated = _json_clone(state)
    updated["phase"] = "reviewer-decision"
    updated["pending_action"] = "await-reviewer-decision"
    updated["reviewer_decision_slot"] = slot
    return updated


def prepare_reviewer_retry(state: Mapping[str, Any], slot: str) -> dict[str, Any]:
    validate_state(state)
    if (
        state["status"] != "active"
        or state["phase"] != "reviewer-decision"
        or state["pending_action"] != "await-reviewer-decision"
        or state["reviewer_decision_slot"] != slot
        or state["reviewer_slots"].get(slot, {}).get("status") != "failed"
    ):
        raise StateError("reviewer retry does not match the pending failed slot")
    updated = _json_clone(state)
    updated["phase"] = "review-round"
    updated["pending_action"] = "retry-reviewer"
    return updated


def mark_slot_result(
    state: Mapping[str, Any],
    slot: str,
    *,
    succeeded: bool,
    output_path: Optional[str],
    attempt: int,
    output_digest: Optional[str] = None,
    state_dir: Optional[PathInput] = None,
) -> dict[str, Any]:
    validate_state(state)
    if state["status"] != "active" or slot not in REVIEWER_SLOTS:
        raise StateError("unknown reviewer slot")
    updated = _json_clone(state)
    record = updated["reviewer_slots"][slot]
    expected_attempt = int(record["attempt"])
    if type(attempt) is not int or attempt != expected_attempt:
        raise StateError(f"stale reviewer attempt for slot {slot}")
    if succeeded and record["status"] != "running":
        raise StateError("only a running reviewer slot can succeed")
    if not succeeded and record["status"] not in {"launching", "running"}:
        raise StateError("only a launching or running reviewer slot can fail")
    if succeeded:
        expected = Path(f"round-{state['round']}") / f"{slot}.md"
        if state_dir is None or output_path is None or Path(output_path) != expected:
            raise StateError(f"successful {slot} reviewer requires {expected}")
        root = Path(state_dir).resolve()
        absolute = root / expected
        try:
            info = absolute.lstat()
        except FileNotFoundError as exc:
            raise StateError(f"reviewer output is missing: {expected}") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise StateError(f"reviewer output is not a regular file: {expected}")
        data = absolute.read_bytes()
        if not data.strip():
            raise StateError(f"reviewer output is empty: {expected}")
        actual_digest = _sha256(data)
        if output_digest != actual_digest:
            raise StateError(f"reviewer output digest mismatch: {expected}")
        record.update(
            status="completed",
            output_path=expected.as_posix(),
            output_digest=actual_digest,
        )
    else:
        if output_path is not None:
            raise StateError("failed reviewer must not record a successful output")
        record.update(status="failed", output_path=None, output_digest=None)
    if updated["pending_action"] == "run-reviewers":
        next_failed = next(
            (
                candidate
                for candidate in REVIEWER_SLOTS
                if updated["reviewer_slots"].get(candidate, {}).get("status")
                == "failed"
                and int(updated["reviewer_slots"][candidate].get("attempt", 0)) >= 2
            ),
            None,
        )
        if next_failed is not None:
            updated["phase"] = "reviewer-decision"
            updated["pending_action"] = "await-reviewer-decision"
            updated["reviewer_decision_slot"] = next_failed
    return updated


def waive_slot(state: Mapping[str, Any], slot: str, *, reason: str) -> dict[str, Any]:
    validate_state(state)
    if (
        state["status"] != "active"
        or state["phase"] != "reviewer-decision"
        or state["pending_action"] != "await-reviewer-decision"
        or state["reviewer_decision_slot"] != slot
        or slot not in REVIEWER_SLOTS
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        raise StateError("waiving a reviewer requires a slot and reason")
    updated = _json_clone(state)
    record = updated["reviewer_slots"].get(slot, {})
    if record.get("status") != "failed":
        raise StateError("only a failed reviewer slot can be waived")
    record.update(status="waived", waiver_reason=reason.strip())
    next_failed = next(
        (
            candidate
            for candidate in REVIEWER_SLOTS
            if updated["reviewer_slots"].get(candidate, {}).get("status") == "failed"
            and int(updated["reviewer_slots"][candidate].get("attempt", 0)) >= 2
        ),
        None,
    )
    if next_failed is None:
        updated["phase"] = "review-round"
        updated["pending_action"] = "run-reviewers"
        updated["reviewer_decision_slot"] = None
    else:
        updated["phase"] = "reviewer-decision"
        updated["pending_action"] = "await-reviewer-decision"
        updated["reviewer_decision_slot"] = next_failed
    return updated


def _validate_reviewer_records(
    state: Mapping[str, Any], cycle_dir: Optional[PathInput] = None
) -> None:
    statuses: dict[str, Any] = {}
    for slot in REVIEWER_SLOTS:
        record = state["reviewer_slots"].get(slot, {})
        status_value = record.get("status")
        statuses[slot] = status_value
        if status_value == "completed":
            expected = Path(f"round-{state['round']}") / f"{slot}.md"
            digest = record.get("output_digest")
            if (
                record.get("output_path") != expected.as_posix()
                or not isinstance(digest, str)
                or not DIGEST_RE.fullmatch(digest)
            ):
                raise StateError(f"reviewer output metadata is invalid: {slot}")
            if cycle_dir is not None:
                absolute = Path(cycle_dir).resolve() / expected
                try:
                    info = absolute.lstat()
                except FileNotFoundError as exc:
                    raise StateError(f"reviewer output is missing: {expected}") from exc
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    raise StateError(f"reviewer output is not regular: {expected}")
                data = absolute.read_bytes()
                if not data.strip() or _sha256(data) != digest:
                    raise StateError(f"reviewer output changed: {expected}")
        elif status_value == "waived":
            if not str(record.get("waiver_reason", "")).strip():
                raise StateError(f"waived reviewer lacks a reason: {slot}")
        else:
            continue
    if any(value not in {"completed", "waived"} for value in statuses.values()):
        raise StateError(f"reviewer round is incomplete: {statuses}")


def mark_round_reviewed(
    state: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    cycle_dir: PathInput,
) -> dict[str, Any]:
    validate_state(state)
    if (
        state["status"] != "active"
        or state["phase"] != "review-round"
        or state["pending_action"] != "run-reviewers"
    ):
        raise StateError("mark_round_reviewed requires an active reviewer round")
    _validate_reviewer_records(state, cycle_dir)
    if dict(snapshot) != state.get("round_snapshot"):
        raise StateError("working tree changed while reviewers were running")
    updated = _json_clone(state)
    updated["reviewed_snapshot"] = copy.deepcopy(dict(snapshot))
    updated["phase"] = "consolidation"
    updated["pending_action"] = "consolidate-round"
    updated["round_results"] = {
        "round": updated["round"],
        "gaps_recorded": False,
        "findings_recorded": False,
    }
    if all(
        updated["reviewer_slots"].get(slot, {}).get("status") == "completed"
        for slot in REVIEWER_SLOTS
    ):
        updated["full_review_rounds"] = sorted(
            {*updated["full_review_rounds"], updated["round"]}
        )
    return updated


def set_await_user_decision(state: Mapping[str, Any]) -> dict[str, Any]:
    validate_state(state)
    if (
        state["status"] != "active"
        or state["phase"] != "decision"
        or state["pending_action"] != "await-user-decision"
    ):
        raise StateError("user decision wait requires an active reviewed round")
    updated = _json_clone(state)
    updated["phase"] = "decision"
    updated["pending_action"] = "await-user-decision"
    return updated


def abort_state(state: Mapping[str, Any], reason: str) -> dict[str, Any]:
    validate_state(state)
    if state["status"] != "active" or not isinstance(reason, str) or not reason.strip():
        raise StateError("only an active cycle can be aborted with a reason")
    in_flight = [
        slot
        for slot in REVIEWER_SLOTS
        if state["reviewer_slots"].get(slot, {}).get("status")
        in {"launching", "running"}
    ]
    if in_flight:
        raise StateError(f"cannot abort while reviewer jobs may be active: {in_flight}")
    updated = _json_clone(state)
    updated.update(status="aborted", phase="aborted", pending_action="none")
    updated["abort_reason"] = reason
    return updated


def _validated_source_rounds(finding: Mapping[str, Any]) -> list[int]:
    raw_rounds = finding.get("source_rounds")
    if (
        not isinstance(raw_rounds, list)
        or not raw_rounds
        or any(type(value) is not int or value < 1 for value in raw_rounds)
    ):
        raise StateError("finding source_rounds must be positive review-round integers")
    return sorted(set(raw_rounds))


def dedupe_findings(findings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Merge only matching stable root-cause IDs, never file:line alone."""

    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in findings:
        item = _json_clone(raw)
        item["source_rounds"] = _validated_source_rounds(item)
        finding_id = item.get("id")
        if not isinstance(finding_id, str) or not SAFE_ID_RE.fullmatch(finding_id):
            raise StateError("finding has invalid stable id")
        if finding_id not in merged:
            merged[finding_id] = item
            order.append(finding_id)
            continue
        previous = merged[finding_id]
        identity_fields = ("scope", "issue", "rule")
        if any(previous.get(key) != item.get(key) for key in identity_fields):
            raise StateError(f"stable finding id collision: {finding_id}")
        rounds = set(_validated_source_rounds(previous))
        rounds.update(item["source_rounds"])
        previous["source_rounds"] = sorted(rounds)
        previous_severity = str(previous.get("severity", "")).lower()
        item_severity = str(item.get("severity", "")).lower()
        if item_severity:
            if item_severity not in SEVERITY_RANK:
                raise StateError(f"unknown finding severity: {item_severity}")
            if (
                previous_severity not in SEVERITY_RANK
                or SEVERITY_RANK[item_severity] > SEVERITY_RANK[previous_severity]
            ):
                previous["severity"] = item_severity
        for key in ("disposition", "reusable", "coverage", "review_date"):
            if key in item:
                previous[key] = copy.deepcopy(item[key])
    return [merged[finding_id] for finding_id in order]


def record_requirement_gaps(
    state: Mapping[str, Any], gaps: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Replace the independently verified requirement-gap ledger."""

    validate_state(state)
    if (
        state["status"] != "active"
        or state["phase"] != "consolidation"
        or state["pending_action"] != "consolidate-round"
    ):
        raise StateError("requirement gaps require the active consolidation phase")
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    finding_ids = {str(item.get("id")) for item in state["findings"]}
    for raw in gaps:
        item = _json_clone(raw)
        item_id = item.get("id")
        if not isinstance(item_id, str) or not SAFE_ID_RE.fullmatch(item_id):
            raise StateError("requirement gap has an invalid stable id")
        if item_id in ids:
            raise StateError(f"duplicate requirement gap id: {item_id}")
        if item_id in finding_ids:
            raise StateError(f"ledger id is already used by a finding: {item_id}")
        if str(item.get("severity", "")).lower() not in BLOCKING_SEVERITIES:
            raise StateError("requirement gap severity must be critical or warning")
        if item.get("disposition") not in FINAL_DISPOSITIONS | {
            "open",
            "false-positive",
        }:
            raise StateError("requirement gap has an invalid disposition")
        ids.add(item_id)
        normalized.append(item)
    updated = _json_clone(state)
    for item in updated["requirement_gaps"]:
        updated["decision_log"].pop(str(item.get("id")), None)
    updated["requirement_gaps"] = normalized
    updated["round_results"]["gaps_recorded"] = True
    return updated


def record_verified_findings(
    state: Mapping[str, Any], findings: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Merge main-agent-verified Codex findings into the durable ledger."""

    validate_state(state)
    if (
        state["status"] != "active"
        or state["phase"] != "consolidation"
        or state["pending_action"] != "consolidate-round"
    ):
        raise StateError("findings require the active consolidation phase")
    normalized: list[dict[str, Any]] = []
    gap_ids = {str(item.get("id")) for item in state["requirement_gaps"]}
    for raw in findings:
        item = _json_clone(raw)
        required = {
            "id",
            "scope",
            "issue",
            "rule",
            "severity",
            "disposition",
            "reusable",
            "source_rounds",
        }
        missing = required.difference(item)
        if missing:
            raise StateError(f"verified finding is missing fields: {sorted(missing)}")
        if str(item["severity"]).lower() not in SEVERITY_RANK:
            raise StateError("verified finding has an invalid severity")
        if str(item["id"]) in gap_ids:
            raise StateError(
                f"ledger id is already used by a requirement gap: {item['id']}"
            )
        if item["disposition"] not in FINAL_DISPOSITIONS | {
            "open",
            "false-positive",
        }:
            raise StateError("verified finding has an invalid disposition")
        if not isinstance(item["reusable"], bool):
            raise StateError("verified finding reusable must be boolean")
        source_rounds = _validated_source_rounds(item)
        if source_rounds != [state["round"]]:
            raise StateError(
                "new findings must identify exactly the current completed review round"
            )
        if item["reusable"]:
            try:
                _validate_learning_metadata(item)
            except PersistenceError as exc:
                raise StateError(
                    f"reusable finding metadata is invalid: {exc}"
                ) from exc
        normalized.append(item)
    updated = _json_clone(state)
    for item in normalized:
        updated["decision_log"].pop(str(item["id"]), None)
    updated["findings"] = dedupe_findings([*updated["findings"], *normalized])
    updated["round_results"]["findings_recorded"] = True
    return updated


def consolidate_review_round(state: Mapping[str, Any]) -> dict[str, Any]:
    """Attest that both empty-or-populated round result ledgers were recorded."""

    validate_state(state)
    results = state["round_results"]
    if (
        state["status"] != "active"
        or state["phase"] != "consolidation"
        or state["pending_action"] != "consolidate-round"
        or results["round"] != state["round"]
        or not results["gaps_recorded"]
        or not results["findings_recorded"]
    ):
        raise StateError(
            "round consolidation requires recorded gap and finding results"
        )
    updated = _json_clone(state)
    updated["round_consolidated"] = updated["round"]
    updated["phase"] = "decision"
    updated["pending_action"] = "await-user-decision"
    return updated


def reopen_consolidation(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return a reviewed decision state to ledger correction without a new round."""

    validate_state(state)
    if (
        state["status"] != "active"
        or state["phase"] != "decision"
        or state["pending_action"] != "await-user-decision"
        or state["round_consolidated"] != state["round"]
    ):
        raise StateError("only a consolidated decision state can be reopened")
    updated = _json_clone(state)
    updated["phase"] = "consolidation"
    updated["pending_action"] = "consolidate-round"
    updated["round_consolidated"] = max(0, updated["round"] - 1)
    updated["round_results"] = {
        "round": updated["round"],
        "gaps_recorded": False,
        "findings_recorded": False,
    }
    updated["decision_log"] = {}
    return updated


def amend_finding_metadata(
    state: Mapping[str, Any], amendments: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Correct persistence-only metadata without inventing a new source round."""

    validate_state(state)
    if (
        state["status"] != "active"
        or state["phase"] != "decision"
        or state["pending_action"] != "await-user-decision"
        or state["round_consolidated"] != state["round"]
    ):
        raise StateError("finding metadata amendments require a decision state")
    updated = _json_clone(state)
    by_id = {str(item.get("id")): item for item in updated["findings"]}
    seen: set[str] = set()
    for raw in amendments:
        amendment = _json_clone(raw)
        if set(amendment) != {"id", "review_date", "coverage"}:
            raise StateError(
                "metadata amendment requires exactly id, review_date, and coverage"
            )
        finding_id = str(amendment["id"])
        if finding_id in seen:
            raise StateError(f"duplicate metadata amendment id: {finding_id}")
        finding = by_id.get(finding_id)
        if finding is None or finding.get("reusable") is not True:
            raise StateError(
                f"metadata amendment requires a reusable finding: {finding_id}"
            )
        candidate = copy.deepcopy(finding)
        candidate["review_date"] = amendment["review_date"]
        candidate["coverage"] = copy.deepcopy(amendment["coverage"])
        try:
            _validate_learning_metadata(candidate)
        except PersistenceError as exc:
            raise StateError(f"finding metadata is invalid: {exc}") from exc
        finding["review_date"] = candidate["review_date"]
        finding["coverage"] = candidate["coverage"]
        seen.add(finding_id)
    return updated


def apply_user_decisions(
    state: Mapping[str, Any], decisions: Mapping[str, str]
) -> dict[str, Any]:
    """Apply explicit final dispositions without mutating unrelated entries."""

    validate_state(state)
    if (
        state["status"] != "active"
        or state["phase"] != "decision"
        or state["pending_action"] != "await-user-decision"
    ):
        raise StateError("user decisions require the active decision phase")
    if not isinstance(decisions, Mapping):
        raise StateError("decisions must be an id-to-disposition object")
    updated = _json_clone(state)
    known: dict[str, tuple[str, dict[str, Any]]] = {}
    for collection_name in ("requirement_gaps", "findings"):
        for item in updated[collection_name]:
            item_id = str(item.get("id"))
            if item_id in known:
                raise StateError(f"ambiguous ledger id across collections: {item_id}")
            known[item_id] = (collection_name, item)
    for item_id, disposition in decisions.items():
        if item_id not in known:
            raise StateError(f"decision references an unknown ledger id: {item_id}")
        collection_name, item = known[item_id]
        severity = str(item.get("severity", "")).lower()
        if disposition == "false-positive":
            item["disposition"] = disposition
            updated["decision_log"][item_id] = {
                "disposition": disposition,
                "round": updated["round"],
            }
            continue
        if collection_name == "requirement_gaps" or severity in BLOCKING_SEVERITIES:
            allowed = {"해결됨", "사용자 수용", "보류"}
        else:
            allowed = {"해결됨", "제안됨"}
        if disposition not in allowed:
            raise StateError(
                f"invalid disposition {disposition!r} for ledger id {item_id}"
            )
        if (
            collection_name == "findings"
            and severity in BLOCKING_SEVERITIES
            and disposition == "해결됨"
            and not any(
                reviewed_round > max(_validated_source_rounds(item))
                for reviewed_round in state["full_review_rounds"]
            )
        ):
            raise StateError(
                f"resolved blocker {item_id} requires a later completed full review round"
            )
        item["disposition"] = disposition
        updated["decision_log"][item_id] = {
            "disposition": disposition,
            "round": updated["round"],
        }
    return updated


def finalize_for_persistence(
    state: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    validate_state(state)
    if state["status"] != "active":
        raise StateError("only an active cycle can be finalized")
    if state["phase"] != "decision" or state["pending_action"] != "await-user-decision":
        raise StateError("finalize requires a completed review decision state")
    if state["round_consolidated"] != state["round"]:
        raise StateError("finalize requires explicit current-round consolidation")
    _validate_reviewer_records(state)
    verify_reviewed_snapshot(state, snapshot)
    updated = _json_clone(state)
    updated["findings"] = dedupe_findings(updated["findings"])
    for collection_name in ("requirement_gaps", "findings"):
        for item in updated[collection_name]:
            disposition = item.get("disposition")
            if disposition not in FINAL_DISPOSITIONS | {"false-positive"}:
                raise StateError(
                    f"{collection_name} item lacks final disposition: {item.get('id')}"
                )
            severity = str(item.get("severity", "")).lower()
            if collection_name == "findings" and severity not in SEVERITY_RANK:
                raise StateError(f"finding has unknown severity: {item.get('id')}")
            if severity in BLOCKING_SEVERITIES and disposition == "제안됨":
                raise StateError("blocking findings cannot finish as suggestions")
            if (
                collection_name == "findings"
                and severity in BLOCKING_SEVERITIES
                and disposition == "해결됨"
                and not any(
                    reviewed_round > max(_validated_source_rounds(item))
                    for reviewed_round in updated["full_review_rounds"]
                )
            ):
                raise StateError(
                    f"resolved blocker {item.get('id')} requires a later completed "
                    "full review round"
                )
            if collection_name == "requirement_gaps" and disposition == "제안됨":
                raise StateError("requirement gaps cannot finish as suggestions")
            if disposition != "false-positive" and (
                collection_name == "requirement_gaps" or severity in BLOCKING_SEVERITIES
            ):
                decision = updated["decision_log"].get(str(item.get("id")))
                if not isinstance(decision, dict) or decision != {
                    "disposition": disposition,
                    "round": updated["round"],
                }:
                    raise StateError(
                        f"blocking ledger item lacks current decision provenance: "
                        f"{item.get('id')}"
                    )
    selected = [
        finding
        for finding in updated["findings"]
        if finding.get("reusable") is True
        and finding.get("disposition") in FINAL_DISPOSITIONS
    ]
    if selected:
        root = Path(updated["repo_root"])
        candidates: dict[str, bytes] = {}
        try:
            for name in TARGET_NAMES:
                target = _TargetSnapshot(root / name)
                try:
                    original = target.data.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise PersistenceError(f"{name} is not UTF-8") from exc
                candidates[name] = build_guidance_candidate(
                    original, selected, name
                ).encode("utf-8")
            if _candidate_entry_signature(
                candidates[TARGET_NAMES[0]]
            ) != _candidate_entry_signature(candidates[TARGET_NAMES[1]]):
                raise PersistenceError(
                    "AGENTS.md and CLAUDE.md managed feedback histories conflict"
                )
        except PersistenceError as exc:
            raise StateError(f"persistence preflight failed: {exc}") from exc
    updated.update(
        status="terminal-pending-persistence",
        phase="persist-feedback",
        pending_action="persist-feedback",
    )
    return updated


def select_persistable_findings(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_state(state)
    selected = []
    for finding in dedupe_findings(state["findings"]):
        if (
            finding.get("reusable") is True
            and finding.get("disposition") in FINAL_DISPOSITIONS
        ):
            selected.append(finding)
    return selected


def read_state(path: PathInput) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read valid state JSON: {path}") from exc
    if not isinstance(value, dict):
        raise StateError("state root must be an object")
    validate_state(value)
    return value


def atomic_write_json(path: PathInput, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temp_path = Path(raw_temp)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        _fsync_directory(target.parent)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        temp_path.unlink(missing_ok=True)
        raise


def create_state_dir(state_dir: PathInput, state: Mapping[str, Any]) -> Path:
    validate_state(state)
    directory = Path(state_dir).resolve()
    if directory != _expected_state_file(state).parent:
        raise StateError("review state must use the repository git directory")
    with _persistence_lock(directory):
        if _lexists(directory):
            try:
                info = directory.lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                    raise StateError(
                        f"review state path is not a directory: {directory}"
                    )
                if any(directory.iterdir()):
                    raise StateError(f"review state already exists: {directory}")
                directory.rmdir()
            except OSError as exc:
                raise StateError(
                    f"cannot recover empty review state directory: {directory}"
                ) from exc
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{directory.name}.init-",
                dir=directory.parent,
            )
        )
        temporary.chmod(0o700)
        try:
            atomic_write_json(temporary / STATE_FILE, state)
            _rename_noreplace(temporary, directory)
            _fsync_directory(directory.parent)
        except BaseException:
            try:
                shutil.rmtree(temporary)
            except OSError:
                pass
            raise
    return directory / STATE_FILE


def _expected_state_file(state: Mapping[str, Any]) -> Path:
    git_dir = Path(
        _run_git(Path(state["repo_root"]), "rev-parse", "--absolute-git-dir")
        .decode()
        .strip()
    ).resolve()
    return git_dir / STATE_DIR_NAME / STATE_FILE


def _validate_state_file_path(path: Path, state: Mapping[str, Any]) -> None:
    if path.resolve() != _expected_state_file(state):
        raise StateError("state path is not the repository review ledger")


def _parse_json_argument(raw: str, expected: Any) -> Any:
    if not isinstance(raw, str):
        raise StateError("CLI JSON argument is required")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StateError("CLI JSON argument is invalid") from exc
    if not isinstance(value, expected):
        if isinstance(expected, tuple):
            label = " or ".join(item.__name__ for item in expected)
        else:
            label = expected.__name__
        raise StateError(f"CLI JSON argument must be {label}")
    return value


def _validate_learning_metadata(finding: Mapping[str, Any]) -> None:
    required = {
        "id",
        "scope",
        "rule",
        "review_date",
        "disposition",
        "reusable",
        "coverage",
    }
    missing = required.difference(finding)
    if missing:
        raise PersistenceError(f"finding is missing fields: {sorted(missing)}")
    if not SAFE_ID_RE.fullmatch(str(finding["id"])):
        raise PersistenceError("invalid finding id")
    if finding["reusable"] is not True:
        raise PersistenceError("persistable finding reusable must be true")
    for key in ("scope", "rule", "review_date"):
        value = finding[key]
        if (
            not isinstance(value, str)
            or not value.strip()
            or "\n" in value
            or "\r" in value
        ):
            raise PersistenceError(f"finding {key} must be one non-empty line")
        if "<!--" in value or "-->" in value or "\x00" in value:
            raise PersistenceError(f"finding {key} contains unsafe markup")
    if UNSAFE_TEXT_RE.search(finding["rule"]):
        raise PersistenceError("finding rule appears to contain sensitive data")
    if "`" in finding["scope"]:
        raise PersistenceError("finding scope contains unsafe Markdown")
    if not DATE_RE.fullmatch(finding["review_date"]):
        raise PersistenceError("finding review_date must use YYYY-MM-DD")
    try:
        date.fromisoformat(finding["review_date"])
    except ValueError as exc:
        raise PersistenceError("finding review_date is not a calendar date") from exc
    coverage = finding["coverage"]
    if not isinstance(coverage, dict) or set(coverage) != set(TARGET_NAMES):
        raise PersistenceError("coverage must describe AGENTS.md and CLAUDE.md")
    for target_name in TARGET_NAMES:
        target_coverage = coverage[target_name]
        if not isinstance(target_coverage, dict):
            raise PersistenceError(f"invalid coverage for {target_name}")
        kind = target_coverage.get("kind")
        if kind == "managed":
            if set(target_coverage) != {"kind"}:
                raise PersistenceError(
                    f"managed coverage for {target_name} has unknown fields"
                )
            continue
        if kind != "external" or set(target_coverage) != {
            "kind",
            "anchor",
            "label",
        }:
            raise PersistenceError(f"invalid coverage for {target_name}")
        anchor = target_coverage["anchor"]
        label = target_coverage["label"]
        if not isinstance(anchor, str) or not anchor or "\x00" in anchor:
            raise PersistenceError("external coverage requires a non-empty anchor")
        if (
            not isinstance(label, str)
            or not label.strip()
            or any(token in label for token in ("\n", "\r", "<!--", "-->", "\x00"))
        ):
            raise PersistenceError("external coverage requires a safe one-line label")


def _validate_learning(finding: Mapping[str, Any]) -> None:
    _validate_learning_metadata(finding)
    if finding["disposition"] not in FINAL_DISPOSITIONS:
        raise PersistenceError("finding disposition is not persistable")


def _rule_hash(finding: Mapping[str, Any]) -> str:
    payload = f"{finding['scope']}\0{finding['rule']}".encode("utf-8")
    return _sha256(payload)


def _encode_anchor(anchor: str) -> str:
    return base64.urlsafe_b64encode(anchor.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_anchor(token: str) -> str:
    try:
        padding = "=" * (-len(token) % 4)
        return base64.b64decode(token + padding, altchars=b"-_", validate=True).decode(
            "utf-8"
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise PersistenceError("managed reference has an invalid anchor") from exc


def _render_entry(finding: Mapping[str, Any], target_name: str) -> str:
    coverage = finding["coverage"][target_name]
    if not isinstance(coverage, dict) or coverage.get("kind") not in {
        "managed",
        "external",
    }:
        raise PersistenceError(f"invalid coverage for {target_name}")
    kind = "rule" if coverage["kind"] == "managed" else "reference"
    if kind == "rule":
        detail = finding["rule"]
        anchor_token = "-"
    else:
        anchor = coverage.get("anchor")
        label = coverage.get("label")
        if (
            not isinstance(anchor, str)
            or not anchor
            or not isinstance(label, str)
            or not label
        ):
            raise PersistenceError("external coverage requires anchor and label")
        if any(token in label for token in ("\n", "\r", "<!--", "-->")):
            raise PersistenceError("external coverage label is unsafe")
        if any(token in anchor for token in ("\n", "\r", "<!--", "-->", "\x00")):
            raise PersistenceError("external coverage anchor must be one safe line")
        if UNSAFE_TEXT_RE.search(anchor) or UNSAFE_TEXT_RE.search(label):
            raise PersistenceError(
                "external coverage appears to contain sensitive data"
            )
        detail = f"기존 규칙 참조: {label}"
        anchor_token = _encode_anchor(anchor)
    return (
        f"- **`{finding['scope']}`**: {detail} "
        f"(Codex 리뷰 {finding['review_date']}, {finding['disposition']}) "
        f"<!-- feature:codex-review-id:{finding['id']};kind:{kind};"
        f"rule:{_rule_hash(finding)};anchor:{anchor_token} -->"
    )


class _ManagedDocument:
    def __init__(self, text: str):
        self.text = text
        newline_match = re.search(r"\r\n|\n", text)
        self.newline = newline_match.group(0) if newline_match else "\n"
        self.heading_positions = [
            match.start()
            for match in re.finditer(rf"(?m)^{re.escape(HEADING)}[ \t]*\r?$", text)
        ]
        self.start_count = text.count(START_MARKER)
        self.end_count = text.count(END_MARKER)
        self.mode: str
        self.body = ""
        self.body_start = -1
        self.body_end = -1
        if self.start_count == 0 and self.end_count == 0:
            if len(self.heading_positions) > 1:
                raise PersistenceError("duplicate canonical feedback heading")
            self.mode = "insert-after-heading" if self.heading_positions else "append"
            return
        if self.start_count != 1 or self.end_count != 1:
            raise PersistenceError("partial or duplicate feedback markers")
        if len(self.heading_positions) != 1:
            raise PersistenceError(
                "managed markers require exactly one canonical heading"
            )
        start = text.index(START_MARKER)
        end = text.index(END_MARKER)
        if start >= end:
            raise PersistenceError("feedback markers are reversed or nested")
        heading_start = self.heading_positions[0]
        heading_end = text.find("\n", heading_start)
        if heading_end < 0:
            heading_end = len(text)
        if heading_start > start or text[heading_end:start].strip():
            raise PersistenceError("start marker must be first nonblank after heading")
        after_start = start + len(START_MARKER)
        if after_start < len(text) and text[after_start] == "\r":
            after_start += 1
        if after_start < len(text) and text[after_start] == "\n":
            after_start += 1
        self.mode = "replace"
        self.body_start = after_start
        self.body_end = end
        self.body = text[after_start:end]

    def outside_text(self) -> str:
        if self.mode == "replace":
            return self.text[: self.body_start] + self.text[self.body_end :]
        return self.text

    def parsed_entries(self) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        ids: set[str] = set()
        rules: set[str] = set()
        for raw in self.body.splitlines():
            if not raw.strip():
                continue
            match = ENTRY_RE.fullmatch(raw)
            if not match:
                raise PersistenceError("managed body contains an unrecognized entry")
            entry = match.groupdict()
            visible = VISIBLE_ENTRY_RE.fullmatch(entry["visible"])
            if visible is None:
                raise PersistenceError("managed entry has invalid visible metadata")
            entry.update(visible.groupdict())
            if entry["kind"] == "rule" and entry["anchor"] != "-":
                raise PersistenceError("managed rule must not carry an external anchor")
            if entry["kind"] == "rule":
                visible_hash = _sha256(
                    f"{entry['scope']}\0{entry['detail']}".encode("utf-8")
                )
                if visible_hash != entry["rule"]:
                    raise PersistenceError(
                        "visible managed rule does not match its protected hash"
                    )
            if entry["kind"] == "reference":
                if entry["anchor"] == "-":
                    raise PersistenceError("managed reference lacks an external anchor")
                _decode_anchor(entry["anchor"])
                if not entry["detail"].startswith("기존 규칙 참조: "):
                    raise PersistenceError("managed reference has invalid visible text")
            if entry["id"] in ids:
                raise PersistenceError(f"duplicate managed finding id: {entry['id']}")
            if entry["rule"] in rules:
                raise PersistenceError("duplicate managed semantic rule")
            ids.add(entry["id"])
            rules.add(entry["rule"])
            entry["line"] = raw
            entries.append(entry)
        return entries

    def render(self, lines: Sequence[str]) -> str:
        newline = self.newline
        body = "".join(f"{line}{newline}" for line in lines)
        if self.mode == "replace":
            return self.text[: self.body_start] + body + self.text[self.body_end :]
        block = f"{START_MARKER}{newline}{body}{END_MARKER}{newline}"
        if self.mode == "insert-after-heading":
            heading_start = self.heading_positions[0]
            heading_end = self.text.find("\n", heading_start)
            if heading_end < 0:
                heading_end = len(self.text)
                prefix = self.text + newline * 2
                suffix = ""
            else:
                prefix = self.text[: heading_end + 1] + newline
                suffix = self.text[heading_end + 1 :]
            return prefix + block + suffix
        separator = ""
        if self.text and not self.text.endswith(newline * 2):
            separator = newline if self.text.endswith(newline) else newline * 2
        return f"{self.text}{separator}{HEADING}{newline}{newline}{block}"


def build_guidance_candidate(
    original: str,
    findings: Sequence[Mapping[str, Any]],
    target_name: str,
) -> str:
    if target_name not in TARGET_NAMES:
        raise PersistenceError(f"invalid target: {target_name}")
    if not findings:
        return original
    document = _ManagedDocument(original)
    existing = document.parsed_entries()
    by_id = {entry["id"]: entry["line"] for entry in existing}
    existing_by_id = {entry["id"]: entry for entry in existing}
    existing_rule_owner = {entry["rule"]: entry["id"] for entry in existing}
    order = [entry["id"] for entry in existing]
    outside = document.outside_text()
    for entry in existing:
        if entry["kind"] == "reference":
            anchor = _decode_anchor(entry["anchor"])
            if outside.count(anchor) != 1:
                raise PersistenceError(
                    f"stored external anchor for {entry['id']} must occur exactly once"
                )
    for finding in findings:
        _validate_learning(finding)
        finding_id = str(finding["id"])
        rule_hash = _rule_hash(finding)
        previous_entry = existing_by_id.get(finding_id)
        if previous_entry is not None:
            previous_hash = previous_entry["rule"]
            if existing_rule_owner.get(previous_hash) == finding_id:
                del existing_rule_owner[previous_hash]
        owner = existing_rule_owner.get(rule_hash)
        if owner is not None and owner != finding_id:
            raise PersistenceError("selected rule duplicates another managed finding")
        coverage = finding["coverage"][target_name]
        if coverage["kind"] == "external":
            anchor = coverage["anchor"]
            if outside.count(anchor) != 1:
                raise PersistenceError(
                    f"external anchor for {finding_id} must occur exactly once"
                )
        elif outside.count(str(finding["rule"])):
            raise PersistenceError(
                f"managed rule {finding_id} already appears outside the block"
            )
        line = _render_entry(finding, target_name)
        by_id[finding_id] = line
        existing_by_id[finding_id] = {
            "id": finding_id,
            "rule": rule_hash,
            "line": line,
        }
        existing_rule_owner[rule_hash] = finding_id
        if finding_id not in order:
            order.append(finding_id)
    candidate = document.render([by_id[finding_id] for finding_id in order])
    parsed = _ManagedDocument(candidate)
    candidate_entries = parsed.parsed_entries()
    ids = [entry["id"] for entry in candidate_entries]
    for finding in findings:
        if ids.count(str(finding["id"])) != 1:
            raise PersistenceError("candidate lost or duplicated a selected finding")
    return candidate


class _TargetSnapshot:
    def __init__(self, path: Path):
        self.path = path
        try:
            info = path.lstat()
        except FileNotFoundError:
            self.exists = False
            self.data = b""
            self.mode = 0o644
            self.digest = None
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise PersistenceError(f"guidance target is not a regular file: {path}")
        self.exists = True
        self.data = path.read_bytes()
        self.mode = _portable_mode(info.st_mode)
        self.digest = _sha256(self.data)

    def unchanged(self) -> bool:
        try:
            current = self.path.lstat()
        except FileNotFoundError:
            return not self.exists
        if (
            not self.exists
            or not stat.S_ISREG(current.st_mode)
            or stat.S_ISLNK(current.st_mode)
        ):
            return False
        return (
            _sha256(self.path.read_bytes()) == self.digest
            and _portable_mode(current.st_mode) == self.mode
        )


@contextmanager
def _persistence_lock(state_dir: Path):
    lock_path = state_dir.parent / f".{state_dir.name}.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        else:  # pragma: no cover - exercised on Windows
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        acquired = True
        yield
    finally:
        try:
            if acquired:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                else:  # pragma: no cover - exercised on Windows
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(descriptor)


def _path_matches(path: Path, data: bytes, mode: int) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return (
        stat.S_ISREG(info.st_mode)
        and not stat.S_ISLNK(info.st_mode)
        and _sha256(path.read_bytes()) == _sha256(data)
        and _portable_mode(info.st_mode) == _portable_mode(mode)
    )


def _same_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _rename_noreplace(source: PathInput, target: PathInput) -> None:
    """Atomically move source only when target does not already exist."""

    source_path = os.fsencode(source)
    target_path = os.fsencode(target)
    if os.name == "nt":  # os.rename is no-replace on Windows.
        os.rename(source, target)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is not None:
            renameat2.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            renameat2.restype = ctypes.c_int
            result = renameat2(-100, source_path, -100, target_path, 1)
        else:
            machine = os.uname().machine.lower()
            syscall_number = LINUX_RENAMEAT2_SYSCALLS.get(machine)
            syscall = getattr(libc, "syscall", None)
            if syscall_number is None or syscall is None:
                raise PersistenceError("atomic no-replace rename is unavailable")
            syscall.restype = ctypes.c_long
            result = syscall(
                ctypes.c_long(syscall_number),
                ctypes.c_int(-100),
                ctypes.c_char_p(source_path),
                ctypes.c_int(-100),
                ctypes.c_char_p(target_path),
                ctypes.c_uint(1),
            )
    elif sys.platform == "darwin":
        renamex_np = getattr(libc, "renamex_np", None)
        if renamex_np is None:
            raise PersistenceError("atomic no-replace rename is unavailable")
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(source_path, target_path, 0x00000004)
    else:
        raise PersistenceError(
            f"atomic no-replace rename is unsupported on {sys.platform}"
        )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
            os.fsdecode(target_path),
        )


def _artifact_path(target: Path, cycle_id: str, kind: str) -> Path:
    return target.parent / f".{target.name}.feature-review-{cycle_id}.{kind}"


def _lexists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        if os.name == "nt":  # Windows does not expose directory fsync this way.
            return
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError:
            if os.name != "nt":
                raise
    finally:
        os.close(descriptor)


def _write_exact_artifact(path: Path, data: bytes, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


def _unlink_artifact(path: Path, data: bytes, mode: int) -> None:
    if not _lexists(path):
        return
    if not _path_matches(path, data, mode):
        raise PersistenceError(f"transaction artifact changed unexpectedly: {path}")
    path.unlink()
    _fsync_directory(path.parent)


def _candidate_entry_signature(data: bytes) -> list[tuple[str, str, str, str, str]]:
    try:
        document = _ManagedDocument(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise PersistenceError("guidance candidate is not UTF-8") from exc
    return [
        (
            entry["id"],
            entry["rule"],
            entry["scope"],
            entry["review_date"],
            entry["disposition"],
        )
        for entry in document.parsed_entries()
    ]


def persist_feedback(
    state_path: PathInput,
    *,
    cycle_id: Optional[str] = None,
    replace: Optional[Callable[[PathInput, PathInput], None]] = None,
    hook: Optional[Callable[[str, Mapping[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Persist learnings through recoverable move-then-link transactions.

    Moving the current target aside captures the exact bytes present at the
    mutation boundary.  Publishing with a hard link is no-clobber: a file that
    appears concurrently is preserved instead of overwritten.  Deterministic
    candidate/original artifacts make every crash point resumable.
    """

    state_file = Path(state_path).resolve()
    state_dir = state_file.parent
    move_noreplace = replace or _rename_noreplace
    initial_state = read_state(state_file)
    try:
        _validate_state_file_path(state_file, initial_state)
    except StateError as exc:
        raise PersistenceError(str(exc)) from exc
    if cycle_id is not None and initial_state["cycle_id"] != cycle_id:
        raise PersistenceError("cycle_id mismatch")
    with _persistence_lock(state_dir):
        state = read_state(state_file)
        if (
            state["repo_root"] != initial_state["repo_root"]
            or state["cycle_id"] != initial_state["cycle_id"]
            or (cycle_id is not None and state["cycle_id"] != cycle_id)
        ):
            raise PersistenceError("review ledger changed while acquiring its lock")
        pending = (
            state["status"] == "terminal-pending-persistence"
            and state["phase"] == "persist-feedback"
            and state["pending_action"] == "persist-feedback"
        )
        complete = (
            state["status"] == "complete"
            and state["phase"] == "complete"
            and state["pending_action"] == "none"
        )
        if not pending and not complete:
            raise PersistenceError("state is not ready for persistence")
        if pending:
            verify_persistence_snapshot(
                state, capture_repo_snapshot(state["repo_root"])
            )
        findings = select_persistable_findings(state)
        if not findings:
            root = Path(state["repo_root"])
            unexpected_artifacts = [
                _artifact_path(root / name, state["cycle_id"], kind)
                for name in TARGET_NAMES
                for kind in ARTIFACT_KINDS
                if _lexists(_artifact_path(root / name, state["cycle_id"], kind))
            ]
            if unexpected_artifacts:
                raise PersistenceError(
                    "transaction artifacts exist without persistable findings: "
                    f"{unexpected_artifacts}"
                )
            if pending:
                state.update(status="complete", phase="complete", pending_action="none")
                atomic_write_json(state_file, state)
            return {
                "cycle_id": state["cycle_id"],
                "targets": {},
                "changed": False,
            }
        root = Path(state["repo_root"])
        plans: dict[str, dict[str, Any]] = {}
        for name in TARGET_NAMES:
            target = root / name
            candidate_path = _artifact_path(target, state["cycle_id"], "candidate")
            original_path = _artifact_path(target, state["cycle_id"], "original")
            rollback_path = _artifact_path(target, state["cycle_id"], "rollback")
            candidate_preexists = _lexists(candidate_path)
            try:
                original_snapshot = (
                    _TargetSnapshot(original_path) if _lexists(original_path) else None
                )
            except PersistenceError:
                if candidate_preexists and not _lexists(target):
                    try:
                        _rename_noreplace(original_path, target)
                        _fsync_directory(target.parent)
                    except (OSError, ReviewFeedbackError) as recovery_exc:
                        raise PersistenceError(
                            f"cannot restore nonregular moved artifact: {name}"
                        ) from recovery_exc
                    raise PersistenceError(
                        f"nonregular moved artifact restored to target: {name}"
                    )
                raise
            if original_snapshot is not None and not candidate_preexists:
                raise PersistenceError(
                    f"original artifact lacks its matching candidate: {name}"
                )
            current = _TargetSnapshot(target)
            base = original_snapshot or current
            try:
                original_text = base.data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PersistenceError(f"{name} is not UTF-8") from exc
            candidate = build_guidance_candidate(original_text, findings, name)
            candidate_data = candidate.encode("utf-8")
            candidate_mode = base.mode if base.exists else 0o644
            if candidate_preexists and not _path_matches(
                candidate_path, candidate_data, candidate_mode
            ):
                if original_snapshot is not None and not current.exists:
                    try:
                        _rename_noreplace(original_path, target)
                        _fsync_directory(target.parent)
                    except (OSError, ReviewFeedbackError) as recovery_exc:
                        raise PersistenceError(
                            f"candidate conflict left moved artifact in place: {name}"
                        ) from recovery_exc
                    raise PersistenceError(
                        f"candidate conflict restored moved target: {name}"
                    )
                raise PersistenceError(f"candidate artifact conflicts for {name}")
            if _lexists(rollback_path) and not _path_matches(
                rollback_path, candidate_data, candidate_mode
            ):
                if not _lexists(target):
                    try:
                        _rename_noreplace(rollback_path, target)
                        _fsync_directory(target.parent)
                    except (OSError, ReviewFeedbackError) as recovery_exc:
                        raise PersistenceError(
                            f"changed rollback artifact could not be restored: {name}"
                        ) from recovery_exc
                    raise PersistenceError(
                        f"changed rollback artifact restored to target: {name}"
                    )
                raise PersistenceError(f"rollback artifact conflicts for {name}")
            if original_snapshot is not None:
                target_matches = current.exists and _path_matches(
                    target, candidate_data, candidate_mode
                )
                if not current.exists:
                    transaction_state = "moved"
                elif target_matches:
                    transaction_state = "applied"
                elif _path_matches(
                    target, original_snapshot.data, original_snapshot.mode
                ) and _same_file(target, original_path):
                    transaction_state = "restored"
                else:
                    raise PersistenceError(
                        f"transaction target conflicts with saved original: {name}"
                    )
            elif current.exists and current.data == candidate_data:
                transaction_state = "applied" if candidate_preexists else "noop"
            else:
                transaction_state = "original" if current.exists else "absent"
            plans[name] = {
                "name": name,
                "target": target,
                "snapshot": current,
                "expected_original": original_snapshot
                or (current if current.exists else None),
                "candidate": candidate_data,
                "mode": candidate_mode,
                "candidate_path": candidate_path,
                "original_path": original_path,
                "rollback_path": rollback_path,
                "state": transaction_state,
            }

        signatures = {
            name: _candidate_entry_signature(plan["candidate"])
            for name, plan in plans.items()
        }
        if signatures[TARGET_NAMES[0]] != signatures[TARGET_NAMES[1]]:
            raise PersistenceError(
                "AGENTS.md and CLAUDE.md managed feedback histories conflict"
            )

        if complete and any(
            plan["state"] not in {"noop", "applied"} for plan in plans.values()
        ):
            raise PersistenceError(
                "completed persistence targets changed after the recorded commit"
            )

        created_candidates: list[dict[str, Any]] = []
        try:
            for plan in plans.values():
                if plan["state"] == "noop":
                    continue
                candidate_path = plan["candidate_path"]
                if _lexists(candidate_path):
                    if not _path_matches(
                        candidate_path, plan["candidate"], plan["mode"]
                    ):
                        raise PersistenceError(
                            f"candidate artifact conflicts for {plan['name']}"
                        )
                else:
                    _write_exact_artifact(
                        candidate_path, plan["candidate"], plan["mode"]
                    )
                    created_candidates.append(plan)
        except BaseException:
            for plan in created_candidates:
                if not _lexists(plan["original_path"]):
                    try:
                        _unlink_artifact(
                            plan["candidate_path"], plan["candidate"], plan["mode"]
                        )
                    except (OSError, ReviewFeedbackError):
                        pass
            raise

        changed_names: list[str] = []
        applied_names: list[str] = [
            name
            for name, plan in plans.items()
            if plan["state"] in {"applied", "moved"}
        ]
        published_names: list[str] = []
        context: dict[str, Any] = {
            "cycle_id": state["cycle_id"],
            "repo_root": str(root),
        }

        def emit(event: str) -> None:
            if hook is not None:
                hook(event, context)

        def rollback() -> list[str]:
            failures: list[str] = []

            def park_published_target(name: str, plan: Mapping[str, Any]) -> bool:
                target = plan["target"]
                rollback_path = plan["rollback_path"]
                try:
                    _rename_noreplace(target, rollback_path)
                    _fsync_directory(target.parent)
                except (OSError, ReviewFeedbackError) as exc:
                    failures.append(f"{name}: rollback parking failed: {exc}")
                    return False
                if _path_matches(rollback_path, plan["candidate"], plan["mode"]):
                    return True
                try:
                    _rename_noreplace(rollback_path, target)
                    _fsync_directory(target.parent)
                except (OSError, ReviewFeedbackError) as exc:
                    failures.append(
                        f"{name}: changed target was parked and could not be "
                        f"restored: {exc}"
                    )
                    return False
                failures.append(f"{name}: current content is no longer our candidate")
                return False

            for name in reversed(applied_names):
                plan = plans[name]
                target = plan["target"]
                try:
                    original_path = plan["original_path"]
                    if _lexists(original_path):
                        original = plan["expected_original"]
                        original_matches = original is not None and _path_matches(
                            original_path, original.data, original.mode
                        )
                        if not _lexists(target):
                            safe_to_restore = name not in published_names and plan[
                                "state"
                            ] in {"moved", "original"}
                            if not safe_to_restore:
                                failures.append(
                                    f"{name}: target disappeared after publish"
                                )
                                continue
                            try:
                                _rename_noreplace(original_path, target)
                            except OSError as exc:
                                failures.append(
                                    f"{name}: rollback publish failed: {exc}"
                                )
                                continue
                            _fsync_directory(target.parent)
                            if original_matches and not _path_matches(
                                target, original.data, original.mode
                            ):
                                failures.append(f"{name}: rollback verification failed")
                            continue
                        if not original_matches:
                            failures.append(
                                f"{name}: original artifact changed unexpectedly"
                            )
                            continue
                        if not park_published_target(name, plan):
                            continue
                        try:
                            _rename_noreplace(original_path, target)
                        except (OSError, ReviewFeedbackError) as exc:
                            failures.append(f"{name}: rollback publish failed: {exc}")
                            continue
                        _fsync_directory(target.parent)
                        if not _path_matches(target, original.data, original.mode):
                            failures.append(f"{name}: rollback verification failed")
                            continue
                        try:
                            _unlink_artifact(
                                plan["rollback_path"],
                                plan["candidate"],
                                plan["mode"],
                            )
                        except (OSError, ReviewFeedbackError) as exc:
                            failures.append(
                                f"{name}: rollback parked artifact cleanup failed: {exc}"
                            )
                    else:
                        if not _lexists(target):
                            continue
                        if not park_published_target(name, plan):
                            continue
                        try:
                            _unlink_artifact(
                                plan["rollback_path"],
                                plan["candidate"],
                                plan["mode"],
                            )
                        except (OSError, ReviewFeedbackError) as exc:
                            failures.append(
                                f"{name}: rollback parked artifact cleanup failed: {exc}"
                            )
                except OSError as exc:
                    failures.append(f"{name}: rollback failed: {exc}")
            return failures

        committed: Optional[bool] = True if complete else False
        commit_attempted = complete
        try:
            for name, plan in plans.items():
                rollback_path = plan["rollback_path"]
                if not _lexists(rollback_path):
                    continue
                original_path = plan["original_path"]
                if _lexists(original_path):
                    if _lexists(plan["target"]):
                        raise PersistenceError(
                            f"rollback recovery target already exists: {name}"
                        )
                    original = plan["expected_original"]
                    if original is None or not _path_matches(
                        original_path, original.data, original.mode
                    ):
                        raise PersistenceError(
                            f"rollback recovery original changed: {name}"
                        )
                    _rename_noreplace(original_path, plan["target"])
                    _fsync_directory(plan["target"].parent)
                    restored = _TargetSnapshot(plan["target"])
                    if restored.data != original.data or restored.mode != original.mode:
                        raise PersistenceError(
                            f"rollback recovery verification failed: {name}"
                        )
                    plan["snapshot"] = restored
                    plan["expected_original"] = restored
                    plan["state"] = "original"
                    if name in applied_names:
                        applied_names.remove(name)
                _unlink_artifact(rollback_path, plan["candidate"], plan["mode"])
            for plan in plans.values():
                if plan["state"] != "restored":
                    continue
                original = plan["expected_original"]
                if (
                    original is None
                    or not _same_file(plan["target"], plan["original_path"])
                    or not _path_matches(plan["target"], original.data, original.mode)
                ):
                    raise PersistenceError(
                        f"rollback recovery changed before cleanup: {plan['name']}"
                    )
                _unlink_artifact(plan["original_path"], original.data, original.mode)
                plan["state"] = "original"
            emit("candidates-ready")
            if pending:
                verify_persistence_snapshot(
                    state, capture_repo_snapshot(state["repo_root"])
                )
            for name in TARGET_NAMES:
                plan = plans[name]
                if plan["state"] in {"noop", "applied"}:
                    continue
                emit(f"before-replace:{name}")
                if plan["state"] == "original" and not plan["snapshot"].unchanged():
                    raise PersistenceError(
                        f"target changed before transactional move: {name}"
                    )
                if plan["state"] == "original":
                    if _lexists(plan["original_path"]):
                        raise PersistenceError(
                            f"original artifact already exists: {name}"
                        )
                    try:
                        move_noreplace(plan["target"], plan["original_path"])
                    except BaseException:
                        if _lexists(plan["original_path"]) and not _lexists(
                            plan["target"]
                        ):
                            moved_after_error = _TargetSnapshot(plan["original_path"])
                            if (
                                moved_after_error.data == plan["snapshot"].data
                                and moved_after_error.mode == plan["snapshot"].mode
                                and name not in applied_names
                            ):
                                applied_names.append(name)
                        raise
                    if name not in applied_names:
                        applied_names.append(name)
                    _fsync_directory(plan["target"].parent)
                    moved = _TargetSnapshot(plan["original_path"])
                    if (
                        moved.data != plan["snapshot"].data
                        or moved.mode != plan["snapshot"].mode
                    ):
                        raise PersistenceError(
                            f"target changed at transactional move: {name}"
                        )
                if _lexists(plan["target"]):
                    raise PersistenceError(
                        f"concurrent target appeared before publish: {name}"
                    )
                emit(f"before-publish:{name}")
                os.link(
                    plan["candidate_path"],
                    plan["target"],
                    follow_symlinks=False,
                )
                _fsync_directory(plan["target"].parent)
                if name not in applied_names:
                    applied_names.append(name)
                published_names.append(name)
                changed_names.append(name)
                emit(f"after-replace:{name}")
            for name in TARGET_NAMES:
                plan = plans[name]
                if not _path_matches(plan["target"], plan["candidate"], plan["mode"]):
                    raise PersistenceError(f"final verification failed: {name}")
            emit("verified")
            if pending:
                verify_persistence_snapshot(
                    state, capture_repo_snapshot(state["repo_root"])
                )
            for name in TARGET_NAMES:
                plan = plans[name]
                if not _path_matches(plan["target"], plan["candidate"], plan["mode"]):
                    raise PersistenceError(
                        f"target changed before state commit: {name}"
                    )
            if pending:
                state.update(status="complete", phase="complete", pending_action="none")
                commit_attempted = True
                try:
                    atomic_write_json(state_file, state)
                except BaseException:
                    try:
                        committed = read_state(state_file) == state
                    except (OSError, ReviewFeedbackError):
                        committed = None
                    raise
                committed = True
                emit("state-complete")
        except BaseException as exc:
            if committed is False and commit_attempted:
                try:
                    committed = read_state(state_file) == state
                except (OSError, ReviewFeedbackError):
                    committed = None
            if committed is True:
                if isinstance(exc, ReviewFeedbackError):
                    raise
                raise PersistenceError(
                    f"completed persistence recovery failed; artifacts preserved: {exc}"
                ) from exc
            if committed is None:
                raise PersistenceError(
                    "persistence state commit outcome is unknown; targets and "
                    f"artifacts preserved: {exc}"
                ) from exc
            rollback_failures = rollback()
            if rollback_failures:
                raise PersistenceError(
                    f"persistence failed ({exc}); partial rollback: {rollback_failures}"
                ) from exc
            cleanup_failures: list[str] = []
            for plan in plans.values():
                try:
                    if _lexists(plan["original_path"]):
                        cleanup_failures.append(
                            f"{plan['name']}: original artifact remains after rollback"
                        )
                        continue
                    if _lexists(plan["rollback_path"]):
                        cleanup_failures.append(
                            f"{plan['name']}: rollback artifact remains after rollback"
                        )
                        continue
                    _unlink_artifact(
                        plan["candidate_path"], plan["candidate"], plan["mode"]
                    )
                except (OSError, ReviewFeedbackError) as cleanup_exc:
                    cleanup_failures.append(f"{plan['name']}: {cleanup_exc}")
            if cleanup_failures:
                raise PersistenceError(
                    f"persistence failed ({exc}); rollback cleanup failed: "
                    f"{cleanup_failures}"
                ) from exc
            if isinstance(exc, ReviewFeedbackError):
                raise
            raise PersistenceError(
                f"persistence failed and was rolled back: {exc}"
            ) from exc

        cleanup_failures: list[str] = []
        for plan in plans.values():
            try:
                rollback_path = plan["rollback_path"]
                if _lexists(rollback_path):
                    _unlink_artifact(rollback_path, plan["candidate"], plan["mode"])
                original_path = plan["original_path"]
                if _lexists(original_path):
                    original = plan["expected_original"]
                    if original is None:
                        raise PersistenceError(
                            "unexpected original artifact during cleanup: "
                            f"{plan['name']}"
                        )
                    _unlink_artifact(original_path, original.data, original.mode)
                _unlink_artifact(
                    plan["candidate_path"], plan["candidate"], plan["mode"]
                )
            except (OSError, ReviewFeedbackError) as exc:
                cleanup_failures.append(f"{plan['name']}: {exc}")
        if cleanup_failures:
            raise PersistenceError(
                f"guidance persisted but artifact cleanup failed: {cleanup_failures}"
            )

        targets = {
            name: {
                "changed": name in changed_names,
                "status": "updated" if name in changed_names else "already-present",
                "mode": plans[name]["mode"],
                "finding_ids": [finding["id"] for finding in findings],
            }
            for name in TARGET_NAMES
        }
        return {
            "cycle_id": state["cycle_id"],
            "targets": targets,
            "changed": bool(changed_names),
        }


def _state_summary(state: Mapping[str, Any]) -> dict[str, Any]:
    reviewer_slots = copy.deepcopy(state["reviewer_slots"])
    launch_slots = [
        slot
        for slot in REVIEWER_SLOTS
        if reviewer_slots.get(slot, {}).get("status") == "pending"
        or (
            reviewer_slots.get(slot, {}).get("status") == "failed"
            and int(reviewer_slots[slot].get("attempt", 0)) < 2
        )
    ]
    collect_slots = [
        slot
        for slot in REVIEWER_SLOTS
        if reviewer_slots.get(slot, {}).get("status") == "running"
    ]
    launching_slots = [
        slot
        for slot in REVIEWER_SLOTS
        if reviewer_slots.get(slot, {}).get("status") == "launching"
    ]
    return {
        "cycle_id": state["cycle_id"],
        "status": state["status"],
        "phase": state["phase"],
        "pending_action": state["pending_action"],
        "round": state["round"],
        "round_consolidated": state["round_consolidated"],
        "round_results": copy.deepcopy(state["round_results"]),
        "reviewer_slots": reviewer_slots,
        "reviewer_decision_slot": state["reviewer_decision_slot"],
        "launch_slots": launch_slots,
        "launching_slots": launching_slots,
        "collect_slots": collect_slots,
    }


def _cmd_init(args: argparse.Namespace) -> int:
    scope = _parse_json_argument(args.scope_json, (dict, list, str, int, float, bool))
    snapshot = capture_repo_snapshot(args.repo)
    state = initialize_state(
        args.repo, scope, snapshot=snapshot, cycle_id=args.cycle_id
    )
    state_path = _expected_state_file(state)
    create_state_dir(state_path.parent, state)
    result = _state_summary(state)
    result["state_file"] = str(state_path)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    state = read_state(state_path)
    _validate_state_file_path(state_path, state)
    scope = _parse_json_argument(args.scope_json, (dict, list, str, int, float, bool))
    action = resume_action(
        state,
        cycle_id=args.cycle_id,
        repo_root=state["repo_root"],
        scope_identity=scope,
    )
    result = _state_summary(state)
    result["action"] = action
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _cmd_state(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    initial = read_state(state_path)
    _validate_state_file_path(state_path, initial)
    if initial["cycle_id"] != args.cycle_id:
        raise StateError("cycle_id mismatch")
    with _persistence_lock(state_path.parent):
        state = read_state(state_path)
        if (
            state["cycle_id"] != initial["cycle_id"]
            or state["repo_root"] != initial["repo_root"]
            or state["cycle_id"] != args.cycle_id
        ):
            raise StateError("review ledger changed while acquiring its lock")
        action = args.action
        if action in {"slot-running", "slot-success", "slot-failure"} and (
            args.attempt is None or args.attempt < 1
        ):
            raise StateError(f"{action} requires a positive --attempt")
        if action == "begin-round":
            updated = begin_round(state, capture_repo_snapshot(state["repo_root"]))
        elif action == "reserve-launches":
            updated = reserve_launches(
                state, _parse_json_argument(args.payload_json, list)
            )
        elif action == "slot-running":
            updated = mark_slot_running(
                state,
                args.slot,
                job_id=args.job_id,
                attempt=args.attempt,
            )
        elif action == "slot-success":
            expected = state_path.parent / f"round-{state['round']}" / f"{args.slot}.md"
            try:
                output_digest = _sha256(expected.read_bytes())
            except OSError as exc:
                raise StateError(f"cannot read reviewer output: {expected}") from exc
            updated = mark_slot_result(
                state,
                args.slot,
                succeeded=True,
                output_path=f"round-{state['round']}/{args.slot}.md",
                output_digest=output_digest,
                state_dir=state_path.parent,
                attempt=args.attempt,
            )
        elif action == "slot-failure":
            updated = mark_slot_result(
                state,
                args.slot,
                succeeded=False,
                output_path=None,
                attempt=args.attempt,
            )
        elif action == "await-reviewer":
            updated = set_await_reviewer_decision(state, args.slot)
        elif action == "retry-reviewer":
            updated = prepare_reviewer_retry(state, args.slot)
        elif action == "waive-reviewer":
            updated = waive_slot(state, args.slot, reason=args.reason)
        elif action == "round-reviewed":
            updated = mark_round_reviewed(
                state,
                capture_repo_snapshot(state["repo_root"]),
                cycle_dir=state_path.parent,
            )
        elif action == "record-gaps":
            updated = record_requirement_gaps(
                state, _parse_json_argument(args.payload_json, list)
            )
        elif action == "record-findings":
            updated = record_verified_findings(
                state, _parse_json_argument(args.payload_json, list)
            )
        elif action == "consolidate-round":
            updated = consolidate_review_round(state)
        elif action == "reopen-consolidation":
            updated = reopen_consolidation(state)
        elif action == "amend-finding-metadata":
            updated = amend_finding_metadata(
                state, _parse_json_argument(args.payload_json, list)
            )
        elif action == "apply-decisions":
            updated = apply_user_decisions(
                state, _parse_json_argument(args.payload_json, dict)
            )
        elif action == "await-user":
            updated = set_await_user_decision(state)
        elif action == "prepare-rereview":
            updated = prepare_rereview(state, capture_repo_snapshot(state["repo_root"]))
        elif action == "abort":
            updated = abort_state(state, args.reason)
        elif action == "finalize":
            updated = finalize_for_persistence(
                state, capture_repo_snapshot(state["repo_root"])
            )
        else:  # pragma: no cover - argparse constrains this
            raise StateError(f"unsupported state action: {action}")
        created_round_dir: Optional[Path] = None
        if action == "begin-round":
            round_dir = state_path.parent / f"round-{updated['round']}"
            try:
                round_dir.mkdir(mode=0o700)
            except FileExistsError:
                try:
                    info = round_dir.lstat()
                    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                        raise StateError(
                            f"review round path is not a directory: {round_dir}"
                        )
                    if any(round_dir.iterdir()):
                        raise StateError(
                            f"review round directory is not empty: {round_dir}"
                        )
                    round_dir.rmdir()
                    round_dir.mkdir(mode=0o700)
                except OSError as recovery_exc:
                    raise StateError(
                        f"cannot recover empty review round directory: {round_dir}"
                    ) from recovery_exc
            created_round_dir = round_dir
        try:
            atomic_write_json(state_path, updated)
        except BaseException:
            committed: Optional[bool] = None
            try:
                committed = read_state(state_path) == updated
            except (OSError, ReviewFeedbackError):
                pass
            if created_round_dir is not None and committed is False:
                try:
                    created_round_dir.rmdir()
                except OSError:
                    pass
            raise
        print(json.dumps(_state_summary(updated), ensure_ascii=False, sort_keys=True))
    return 0


def _cmd_persist(args: argparse.Namespace) -> int:
    result = persist_feedback(args.state, cycle_id=args.cycle_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def discard_cycle(
    state_path: PathInput, *, cycle_id: str, reason: str
) -> dict[str, Any]:
    """Remove one exact artifact-free terminal review cycle."""

    if not isinstance(reason, str) or not reason.strip():
        raise StateError("discard requires a non-empty reason")
    state_file = Path(state_path).resolve()
    state = read_state(state_file)
    _validate_state_file_path(state_file, state)
    if state["cycle_id"] != cycle_id:
        raise StateError("cycle_id mismatch")
    if state["status"] not in {
        "aborted",
        "complete",
        "terminal-pending-persistence",
    }:
        raise StateError(
            "only an aborted, complete, or terminal-pending cycle can be discarded"
        )
    in_flight = [
        slot
        for slot in REVIEWER_SLOTS
        if state["reviewer_slots"].get(slot, {}).get("status")
        in {"launching", "running"}
    ]
    if in_flight:
        raise StateError(
            f"cannot discard while reviewer jobs may be active: {in_flight}"
        )
    root = Path(state["repo_root"])
    artifacts = [
        _artifact_path(root / name, state["cycle_id"], kind)
        for name in TARGET_NAMES
        for kind in ARTIFACT_KINDS
    ]
    if any(_lexists(path) for path in artifacts):
        raise StateError("cycle has transaction artifacts; run persist recovery first")
    state_dir = state_file.parent
    try:
        info = state_dir.lstat()
    except FileNotFoundError as exc:
        raise StateError("review cycle directory is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise StateError("review cycle path is not a regular directory")
    with _persistence_lock(state_dir):
        locked = read_state(state_file)
        if locked != state:
            raise StateError("review ledger changed while acquiring its lock")
        if any(_lexists(path) for path in artifacts):
            raise StateError(
                "cycle has transaction artifacts; run persist recovery first"
            )
        tombstone = state_dir.parent / (
            f".{state_dir.name}.discard-{state['cycle_id']}-{uuid.uuid4().hex}"
        )
        os.replace(state_dir, tombstone)
        _fsync_directory(state_dir.parent)
        shutil.rmtree(tombstone)
        _fsync_directory(state_dir.parent)
    return {"cycle_id": cycle_id, "discarded": True, "reason": reason.strip()}


def _cmd_discard(args: argparse.Namespace) -> int:
    result = discard_cycle(
        args.state,
        cycle_id=args.cycle_id,
        reason=args.reason,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="initialize an exclusive Codex review ledger"
    )
    init_parser.add_argument("--repo", required=True)
    init_parser.add_argument("--scope-json", required=True)
    init_parser.add_argument("--cycle-id")
    init_parser.set_defaults(handler=_cmd_init)

    resume_parser = subparsers.add_parser(
        "resume", help="resolve the next action for an existing ledger"
    )
    resume_parser.add_argument("--state", required=True)
    resume_parser.add_argument("--cycle-id", required=True)
    resume_parser.add_argument("--scope-json", required=True)
    resume_parser.set_defaults(handler=_cmd_resume)

    state_parser = subparsers.add_parser(
        "state", help="apply one validated review-state transition"
    )
    state_parser.add_argument("--state", required=True)
    state_parser.add_argument("--cycle-id", required=True)
    state_parser.add_argument(
        "--action",
        required=True,
        choices=(
            "begin-round",
            "reserve-launches",
            "slot-running",
            "slot-success",
            "slot-failure",
            "await-reviewer",
            "retry-reviewer",
            "waive-reviewer",
            "round-reviewed",
            "record-gaps",
            "record-findings",
            "consolidate-round",
            "reopen-consolidation",
            "amend-finding-metadata",
            "apply-decisions",
            "await-user",
            "prepare-rereview",
            "abort",
            "finalize",
        ),
    )
    state_parser.add_argument("--slot", choices=REVIEWER_SLOTS)
    state_parser.add_argument("--job-id")
    state_parser.add_argument("--attempt", type=int)
    state_parser.add_argument("--reason")
    state_parser.add_argument("--payload-json")
    state_parser.set_defaults(handler=_cmd_state)

    persist_parser = subparsers.add_parser(
        "persist", help="persist terminal review learnings"
    )
    persist_parser.add_argument("--state", required=True, help="path to state.json")
    persist_parser.add_argument("--cycle-id", required=True)
    persist_parser.set_defaults(handler=_cmd_persist)

    discard_parser = subparsers.add_parser(
        "discard", help="discard one exact artifact-free terminal review cycle"
    )
    discard_parser.add_argument("--state", required=True)
    discard_parser.add_argument("--cycle-id", required=True)
    discard_parser.add_argument("--reason", required=True)
    discard_parser.set_defaults(handler=_cmd_discard)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (ReviewFeedbackError, OSError) as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
