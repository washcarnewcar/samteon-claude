#!/usr/bin/env python3
"""Minimal stdio MCP server for Codex self-improvement skill operations."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict

from skill_store import (
    SkillStoreError,
    archive_skill,
    create_skill,
    curate,
    list_skills,
    load_usage,
    patch_skill,
    pin_skill,
    restore_skill,
    status,
    view_skill,
    write_support_file,
)


def _schema(properties: Dict[str, Any], required: list[str] | None = None) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOLS: Dict[str, Dict[str, Any]] = {
    "codex_self_improvement_status": {
        "description": "Show plugin status, data directory, skill roots, and telemetry counts.",
        "inputSchema": _schema({}),
    },
    "codex_skill_list": {
        "description": "List Codex user/repo skills visible to the self-improvement manager.",
        "inputSchema": _schema({}),
    },
    "codex_skill_view": {
        "description": "Read one skill and record a view event.",
        "inputSchema": _schema({"name": {"type": "string"}}, ["name"]),
    },
    "codex_skill_usage": {
        "description": "Return raw sidecar usage telemetry.",
        "inputSchema": _schema({}),
    },
    "codex_skill_create": {
        "description": "Create a new user/repo Codex skill with validated SKILL.md frontmatter.",
        "inputSchema": _schema(
            {
                "name": {"type": "string"},
                "content": {"type": "string"},
                "root": {"type": "string"},
            },
            ["name", "content"],
        ),
    },
    "codex_skill_patch": {
        "description": "Patch SKILL.md or a supporting file with backup and validation.",
        "inputSchema": _schema(
            {
                "name": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "file_path": {"type": "string", "default": "SKILL.md"},
            },
            ["name", "old_text", "new_text"],
        ),
    },
    "codex_skill_write_file": {
        "description": "Write SKILL.md or a supporting file under references/templates/scripts/assets.",
        "inputSchema": _schema(
            {
                "name": {"type": "string"},
                "file_path": {"type": "string"},
                "content": {"type": "string"},
            },
            ["name", "file_path", "content"],
        ),
    },
    "codex_skill_archive": {
        "description": "Archive a skill reversibly. Pinned skills are protected.",
        "inputSchema": _schema({"name": {"type": "string"}}, ["name"]),
    },
    "codex_skill_restore": {
        "description": "Restore an archived skill.",
        "inputSchema": _schema(
            {
                "name": {"type": "string"},
                "root": {"type": "string"},
            },
            ["name"],
        ),
    },
    "codex_skill_pin": {
        "description": "Pin or unpin a skill. Pin blocks archive/delete but allows patching.",
        "inputSchema": _schema(
            {
                "name": {"type": "string"},
                "pinned": {"type": "boolean", "default": True},
            },
            ["name"],
        ),
    },
    "codex_skill_curate": {
        "description": "Run deterministic curator candidate selection. Dry-run is default.",
        "inputSchema": _schema(
            {
                "dry_run": {"type": "boolean", "default": True},
                "stale_days": {"type": "integer", "default": 30},
                "archive_days": {"type": "integer", "default": 90},
            }
        ),
    },
}


def call_tool(name: str, args: Dict[str, Any]) -> Any:
    args = args or {}
    if name == "codex_self_improvement_status":
        return status()
    if name == "codex_skill_list":
        return list_skills()
    if name == "codex_skill_view":
        return view_skill(args["name"])
    if name == "codex_skill_usage":
        return load_usage()
    if name == "codex_skill_create":
        return create_skill(args["name"], args["content"], root=args.get("root"))
    if name == "codex_skill_patch":
        return patch_skill(
            args["name"],
            args["old_text"],
            args["new_text"],
            file_path=args.get("file_path") or "SKILL.md",
        )
    if name == "codex_skill_write_file":
        return write_support_file(args["name"], args["file_path"], args["content"])
    if name == "codex_skill_archive":
        return archive_skill(args["name"])
    if name == "codex_skill_restore":
        return restore_skill(args["name"], root=args.get("root"))
    if name == "codex_skill_pin":
        return pin_skill(args["name"], bool(args.get("pinned", True)))
    if name == "codex_skill_curate":
        return curate(
            dry_run=bool(args.get("dry_run", True)),
            stale_days=int(args.get("stale_days", 30)),
            archive_days=int(args.get("archive_days", 90)),
        )
    raise SkillStoreError(f"Unknown tool: {name}")


def send(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def result(message_id: Any, value: Any) -> None:
    send({"jsonrpc": "2.0", "id": message_id, "result": value})


def error(message_id: Any, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}})


def handle(message: Dict[str, Any]) -> None:
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        result(
            message_id,
            {
                "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "codex-self-improvement", "version": "0.1.0"},
            },
        )
        return

    if method == "tools/list":
        result(
            message_id,
            {
                "tools": [
                    {"name": name, **spec}
                    for name, spec in sorted(TOOLS.items(), key=lambda item: item[0])
                ]
            },
        )
        return

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments") or {}
        try:
            payload = call_tool(tool_name, args)
            result(
                message_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                        }
                    ],
                    "isError": False,
                },
            )
        except Exception as exc:
            result(
                message_id,
                {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )
        return

    if message_id is not None:
        error(message_id, -32601, f"Unsupported method: {method}")


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            handle(json.loads(line))
        except json.JSONDecodeError as exc:
            error(None, -32700, f"Parse error: {exc}")
        except Exception as exc:
            error(None, -32603, f"Internal error: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

