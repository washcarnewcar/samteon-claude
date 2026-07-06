#!/usr/bin/env python3
"""Local Codex skill store utilities for the self-improvement plugin."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import fcntl
except Exception:  # pragma: no cover - Windows fallback
    fcntl = None

VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ALLOWED_SUPPORT_DIRS = {"references", "templates", "scripts", "assets"}
MAX_SKILL_CHARS = 100_000
MAX_SUPPORT_BYTES = 1_048_576


class SkillStoreError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def plugin_root() -> Path:
    env = os.environ.get("PLUGIN_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    env = os.environ.get("PLUGIN_DATA")
    path = Path(env).expanduser() if env else Path.home() / ".codex-self-improvement"
    path.mkdir(parents=True, exist_ok=True)
    return path


def usage_path() -> Path:
    return data_dir() / "usage.json"


def usage_lock_path() -> Path:
    return data_dir() / "usage.lock"


def events_path() -> Path:
    return data_dir() / "events.jsonl"


def review_signals_path() -> Path:
    return data_dir() / "review-signals.jsonl"


def state_path() -> Path:
    return data_dir() / "state.json"


def normalize_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower())
    name = re.sub(r"-+", "-", name).strip("-._")
    return name[:64]


def validate_name(name: str) -> str:
    name = normalize_name(name)
    if not name or not VALID_NAME_RE.match(name):
        raise SkillStoreError(
            "Invalid skill name. Use lowercase letters, numbers, dots, underscores, or hyphens."
        )
    return name


def default_skill_roots(cwd: Optional[Path] = None) -> List[Path]:
    roots: List[Path] = []
    env = os.environ.get("CODEX_SELF_IMPROVE_SKILL_ROOTS")
    if env:
        for item in env.split(os.pathsep):
            if item.strip():
                roots.append(Path(item).expanduser())
    else:
        cwd = cwd or Path.cwd()
        repo_root = _git_root(cwd) or cwd
        for repo_skills in (
            repo_root / ".agents" / "skills",
            repo_root / ".codex" / "skills",
        ):
            if repo_skills.exists():
                roots.append(repo_skills)
        roots.append(Path.home() / ".agents" / "skills")
        codex_skills = Path.home() / ".codex" / "skills"
        if codex_skills.exists():
            roots.append(codex_skills)

    unique: List[Path] = []
    seen = set()
    for root in roots:
        resolved = root.expanduser().resolve()
        if str(resolved) not in seen:
            unique.append(resolved)
            seen.add(str(resolved))
    return unique


def default_create_root() -> Path:
    env = os.environ.get("CODEX_SELF_IMPROVE_CREATE_ROOT")
    root = Path(env).expanduser() if env else Path.home() / ".codex" / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _git_root(cwd: Path) -> Optional[Path]:
    current = cwd.resolve()
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            return parent
    return None


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


@contextmanager
def usage_lock() -> Iterable[None]:
    if fcntl is None:
        yield
        return
    lock = usage_lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def mutate_usage(mutator: Any) -> Any:
    with usage_lock():
        data = load_usage()
        result = mutator(data)
        save_usage(data)
        return result


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    if not text.startswith("---\n"):
        raise SkillStoreError("SKILL.md must start with YAML frontmatter.")
    end = text.find("\n---", 4)
    if end == -1:
        raise SkillStoreError("SKILL.md frontmatter is not closed.")
    raw = text[4:end]
    body = text[text.find("\n", end + 4) + 1 :]
    meta: Dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"')
    return meta, body


def validate_skill_content(text: str, expected_name: Optional[str] = None) -> None:
    if len(text) > MAX_SKILL_CHARS:
        raise SkillStoreError(f"SKILL.md exceeds {MAX_SKILL_CHARS} characters.")
    meta, body = parse_frontmatter(text)
    name = meta.get("name")
    description = meta.get("description")
    if not name:
        raise SkillStoreError("Frontmatter must include name.")
    if not description:
        raise SkillStoreError("Frontmatter must include description.")
    if expected_name and normalize_name(name) != expected_name:
        raise SkillStoreError(
            f"Frontmatter name '{name}' does not match target skill '{expected_name}'."
        )
    if not body.strip():
        raise SkillStoreError("SKILL.md must include instructions after frontmatter.")


def iter_skill_files(roots: Optional[List[Path]] = None) -> Iterable[Path]:
    roots = roots or default_skill_roots()
    for root in roots:
        if not root.exists():
            continue
        for skill_md in root.rglob("SKILL.md"):
            try:
                rel_parts = skill_md.relative_to(root).parts[:-1]
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel_parts):
                continue
            yield skill_md


def read_skill_name(skill_md: Path) -> str:
    try:
        meta, _ = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        return normalize_name(meta.get("name") or skill_md.parent.name)
    except Exception:
        return normalize_name(skill_md.parent.name)


def find_skill(name: str, include_archived: bool = False) -> Optional[Path]:
    name = validate_name(name)
    for skill_md in iter_skill_files():
        if read_skill_name(skill_md) == name:
            return skill_md.parent
    if include_archived:
        for root in default_skill_roots():
            archived = root / ".archive" / name / "SKILL.md"
            if archived.exists():
                return archived.parent
    return None


def list_skills() -> Dict[str, Any]:
    usage = load_usage()
    skills = []
    for skill_md in iter_skill_files():
        name = read_skill_name(skill_md)
        try:
            meta, _ = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        rec = usage.get("skills", {}).get(name, {})
        skills.append(
            {
                "name": name,
                "description": meta.get("description", ""),
                "path": str(skill_md),
                "root": str(_containing_root(skill_md.parent)),
                "usage": rec,
            }
        )
    skills.sort(key=lambda row: row["name"])
    return {"skills": skills, "roots": [str(p) for p in default_skill_roots()]}


def view_skill(name: str) -> Dict[str, Any]:
    skill_dir = find_skill(name)
    if not skill_dir:
        raise SkillStoreError(f"Skill '{name}' was not found.")
    name = read_skill_name(skill_dir / "SKILL.md")
    record_usage(name, view=True)
    files = []
    for child in sorted(skill_dir.rglob("*")):
        if child.is_file():
            files.append(str(child.relative_to(skill_dir)))
    return {
        "name": name,
        "path": str(skill_dir),
        "content": (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
        "files": files,
    }


def _containing_root(path: Path) -> Path:
    resolved = path.resolve()
    for root in default_skill_roots():
        try:
            resolved.relative_to(root)
            return root
        except ValueError:
            continue
    return default_create_root()


def _safe_relative_path(file_path: str) -> Path:
    rel = Path(file_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise SkillStoreError("file_path must be a safe relative path.")
    if str(rel) == "SKILL.md":
        return rel
    if not rel.parts or rel.parts[0] not in ALLOWED_SUPPORT_DIRS:
        allowed = ", ".join(sorted(ALLOWED_SUPPORT_DIRS))
        raise SkillStoreError(f"Supporting files must live under one of: {allowed}.")
    return rel


def _frontmatter_pinned(skill_dir: Path) -> bool:
    try:
        meta, _ = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    except Exception:
        return False
    return str(meta.get("pinned") or "").strip().lower() in {"1", "true", "yes", "on"}


def backup_skill(skill_dir: Path, reason: str = "manual") -> Dict[str, Any]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = read_skill_name(skill_dir / "SKILL.md")
    base_id = f"{ts}-{name}"
    backup_id = base_id
    dest = data_dir() / "backups" / backup_id
    suffix = 2
    while dest.exists():
        backup_id = f"{base_id}-{suffix}"
        dest = data_dir() / "backups" / backup_id
        suffix += 1
    shutil.copytree(skill_dir, dest)
    manifest = {
        "backup_id": backup_id,
        "skill": name,
        "source": str(skill_dir),
        "created_at": now_iso(),
        "reason": reason,
    }
    atomic_write_json(dest / "manifest.json", manifest)
    return manifest


def load_usage() -> Dict[str, Any]:
    data = load_json(usage_path(), {"version": 1, "skills": {}, "tools": {}})
    if not isinstance(data, dict):
        return {"version": 1, "skills": {}, "tools": {}}
    data.setdefault("version", 1)
    data.setdefault("skills", {})
    data.setdefault("tools", {})
    return data


def save_usage(data: Dict[str, Any]) -> None:
    atomic_write_json(usage_path(), data)


def record_usage(
    name: str,
    *,
    view: bool = False,
    use: bool = False,
    patch: bool = False,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    name = validate_name(name)

    def _mutate(data: Dict[str, Any]) -> Dict[str, Any]:
        rec = data.setdefault("skills", {}).setdefault(
            name,
            {
                "created_at": now_iso(),
                "created_by": created_by or "unknown",
                "state": "active",
                "pinned": False,
                "use_count": 0,
                "view_count": 0,
                "patch_count": 0,
            },
        )
        if created_by and rec.get("created_by") in (None, "unknown"):
            rec["created_by"] = created_by
        if view:
            rec["view_count"] = int(rec.get("view_count") or 0) + 1
            rec["last_viewed_at"] = now_iso()
        if use:
            rec["use_count"] = int(rec.get("use_count") or 0) + 1
            rec["last_used_at"] = now_iso()
        if patch:
            rec["patch_count"] = int(rec.get("patch_count") or 0) + 1
            rec["last_patched_at"] = now_iso()
        if (view or use or patch) and rec.get("state") == "stale":
            rec["state"] = "active"
        return rec

    return mutate_usage(_mutate)


def record_tool_use(tool_name: str, payload: Dict[str, Any]) -> None:
    def _mutate(data: Dict[str, Any]) -> None:
        rec = data.setdefault("tools", {}).setdefault(tool_name, {"count": 0})
        rec["count"] = int(rec.get("count") or 0) + 1
        rec["last_used_at"] = now_iso()
        rec["last_payload_keys"] = sorted(payload.keys())

    mutate_usage(_mutate)
    append_jsonl(events_path(), {"at": now_iso(), "type": "tool", "tool": tool_name})


def create_skill(name: str, content: str, root: Optional[str] = None) -> Dict[str, Any]:
    name = validate_name(name)
    validate_skill_content(content, expected_name=name)
    target_root = Path(root).expanduser().resolve() if root else default_create_root()
    skill_dir = target_root / name
    if skill_dir.exists():
        raise SkillStoreError(f"Skill '{name}' already exists at {skill_dir}.")
    skill_dir.mkdir(parents=True, exist_ok=False)
    atomic_write_text(skill_dir / "SKILL.md", content)
    record_usage(name, created_by="agent")
    return {"action": "create", "name": name, "path": str(skill_dir), "backup": None}


def patch_skill(name: str, old_text: str, new_text: str, file_path: str = "SKILL.md") -> Dict[str, Any]:
    name = validate_name(name)
    skill_dir = find_skill(name)
    if not skill_dir:
        raise SkillStoreError(f"Skill '{name}' was not found.")
    rel = _safe_relative_path(file_path)
    target = skill_dir / rel
    if not target.exists():
        raise SkillStoreError(f"File '{file_path}' does not exist in skill '{name}'.")
    text = target.read_text(encoding="utf-8")
    if old_text not in text:
        raise SkillStoreError("old_text was not found.")
    updated = text.replace(old_text, new_text, 1)
    if rel == Path("SKILL.md"):
        validate_skill_content(updated, expected_name=name)
    backup = backup_skill(skill_dir, reason=f"patch:{file_path}")
    atomic_write_text(target, updated)
    record_usage(name, patch=True)
    return {"action": "patch", "name": name, "file": file_path, "backup": backup["backup_id"]}


def write_support_file(name: str, file_path: str, content: str) -> Dict[str, Any]:
    name = validate_name(name)
    skill_dir = find_skill(name)
    if not skill_dir:
        raise SkillStoreError(f"Skill '{name}' was not found.")
    rel = _safe_relative_path(file_path)
    if rel == Path("SKILL.md"):
        validate_skill_content(content, expected_name=name)
    if len(content.encode("utf-8")) > MAX_SUPPORT_BYTES:
        raise SkillStoreError(f"File exceeds {MAX_SUPPORT_BYTES} bytes.")
    backup = backup_skill(skill_dir, reason=f"write:{file_path}")
    atomic_write_text(skill_dir / rel, content)
    record_usage(name, patch=True)
    return {"action": "write_file", "name": name, "file": file_path, "backup": backup["backup_id"]}


def pin_skill(name: str, pinned: bool = True) -> Dict[str, Any]:
    name = validate_name(name)
    if not find_skill(name, include_archived=True):
        raise SkillStoreError(f"Skill '{name}' was not found.")

    def _mutate(data: Dict[str, Any]) -> None:
        rec = data.setdefault("skills", {}).setdefault(name, {"created_at": now_iso(), "state": "active"})
        rec["pinned"] = bool(pinned)

    mutate_usage(_mutate)
    return {"action": "pin" if pinned else "unpin", "name": name, "pinned": bool(pinned)}


def archive_skill(name: str) -> Dict[str, Any]:
    name = validate_name(name)
    skill_dir = find_skill(name)
    if not skill_dir:
        raise SkillStoreError(f"Skill '{name}' was not found.")
    with usage_lock():
        data = load_usage()
        rec = data.setdefault("skills", {}).setdefault(name, {"created_at": now_iso(), "state": "active"})
        if rec.get("pinned") or _frontmatter_pinned(skill_dir):
            raise SkillStoreError(f"Skill '{name}' is pinned and cannot be archived.")
        root = _containing_root(skill_dir)
        archive_dir = root / ".archive" / name
        if archive_dir.exists():
            raise SkillStoreError(f"Archive destination already exists: {archive_dir}")
        backup = backup_skill(skill_dir, reason="archive")
        archive_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(skill_dir), str(archive_dir))
        rec["state"] = "archived"
        rec["archived_at"] = now_iso()
        save_usage(data)
    return {"action": "archive", "name": name, "path": str(archive_dir), "backup": backup["backup_id"]}


def restore_skill(name: str, root: Optional[str] = None) -> Dict[str, Any]:
    name = validate_name(name)
    roots = [Path(root).expanduser().resolve()] if root else default_skill_roots()
    for skill_root in roots:
        archived = skill_root / ".archive" / name
        if archived.exists():
            dest = skill_root / name
            if dest.exists():
                raise SkillStoreError(f"Restore destination already exists: {dest}")
            shutil.move(str(archived), str(dest))

            def _mutate(data: Dict[str, Any]) -> None:
                rec = data.setdefault("skills", {}).setdefault(name, {"created_at": now_iso()})
                rec["state"] = "active"
                rec["restored_at"] = now_iso()

            mutate_usage(_mutate)
            return {"action": "restore", "name": name, "path": str(dest)}
    raise SkillStoreError(f"Archived skill '{name}' was not found.")


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _latest_activity(record: Dict[str, Any], skill_dir: Path) -> datetime:
    values = [
        record.get("last_used_at"),
        record.get("last_viewed_at"),
        record.get("last_patched_at"),
        record.get("created_at"),
    ]
    parsed = [dt for dt in (_parse_time(v) for v in values) if dt]
    if parsed:
        return max(parsed)
    return datetime.fromtimestamp((skill_dir / "SKILL.md").stat().st_mtime, tz=timezone.utc)


def _use_count(record: Dict[str, Any]) -> int:
    try:
        return int(record.get("use_count") or 0)
    except (TypeError, ValueError):
        return 0


def _archive_days_for(record: Dict[str, Any], base_days: int) -> int:
    if _use_count(record) >= 3:
        return base_days * 2
    return base_days


def curate(dry_run: bool = True, stale_days: int = 30, archive_days: int = 90) -> Dict[str, Any]:
    usage = load_usage()
    now = datetime.now(timezone.utc)
    rows = []
    for item in list_skills()["skills"]:
        name = item["name"]
        rec = usage.get("skills", {}).get(name, {})
        skill_dir = Path(item["path"]).parent
        latest = _latest_activity(rec, skill_dir)
        age_days = (now - latest).days
        pinned = bool(rec.get("pinned")) or _frontmatter_pinned(skill_dir)
        created_by = str(rec.get("created_by") or "user")
        action = "keep"
        reason = "recent"
        if created_by != "agent":
            reason = f"protected {created_by} skill"
        elif pinned:
            reason = "pinned"
        elif age_days >= _archive_days_for(rec, archive_days):
            action = "archive"
            reason = f"inactive for {age_days} days"
        elif age_days >= stale_days:
            action = "mark_stale"
            reason = f"inactive for {age_days} days"
        elif rec.get("state") == "stale":
            action = "reactivate"
            reason = "recent activity"
        rows.append(
            {
                "name": name,
                "candidate_action": action,
                "reason": reason,
                "age_days": age_days,
                "pinned": pinned,
                "created_by": created_by,
                "use_count": _use_count(rec),
                "path": item["path"],
            }
        )
    applied = []
    if not dry_run:
        for row in rows:
            if row["candidate_action"] == "archive":
                applied.append(archive_skill(row["name"]))
            elif row["candidate_action"] == "mark_stale":
                def _mark_stale(data: Dict[str, Any], skill_name: str = row["name"]) -> None:
                    rec = data.setdefault("skills", {}).setdefault(skill_name, {"created_at": now_iso()})
                    rec["state"] = "stale"

                mutate_usage(_mark_stale)
                applied.append({"action": "mark_stale", "name": row["name"]})
            elif row["candidate_action"] == "reactivate":
                def _reactivate(data: Dict[str, Any], skill_name: str = row["name"]) -> None:
                    rec = data.setdefault("skills", {}).setdefault(skill_name, {"created_at": now_iso()})
                    rec["state"] = "active"

                mutate_usage(_reactivate)
                applied.append({"action": "reactivate", "name": row["name"]})
    return {"dry_run": dry_run, "stale_days": stale_days, "archive_days": archive_days, "candidates": rows, "applied": applied}


def status() -> Dict[str, Any]:
    usage = load_usage()
    return {
        "plugin_root": str(plugin_root()),
        "data_dir": str(data_dir()),
        "skill_roots": [str(p) for p in default_skill_roots()],
        "skill_count": len(list_skills()["skills"]),
        "tracked_skill_count": len(usage.get("skills", {})),
        "tracked_tool_count": len(usage.get("tools", {})),
        "auto_continue": os.environ.get("CODEX_SELF_IMPROVE_AUTO", "").lower() in {"1", "true", "yes", "on"},
    }


def load_state() -> Dict[str, Any]:
    state = load_json(state_path(), {})
    return state if isinstance(state, dict) else {}


def save_state(state: Dict[str, Any]) -> None:
    atomic_write_json(state_path(), state)


def record_review_signal(signal: Dict[str, Any]) -> None:
    append_jsonl(review_signals_path(), signal)


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
