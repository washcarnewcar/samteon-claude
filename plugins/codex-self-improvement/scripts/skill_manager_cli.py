#!/usr/bin/env python3
"""CLI wrapper for the Codex self-improvement skill store."""

from __future__ import annotations

import argparse
import json
import sys

from skill_store import (
    SkillStoreError,
    archive_skill,
    create_skill,
    curate,
    json_dumps,
    list_skills,
    patch_skill,
    pin_skill,
    restore_skill,
    status,
    view_skill,
    write_support_file,
    load_usage,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex self-improvement skill manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    sub.add_parser("list")
    sub.add_parser("usage")

    view = sub.add_parser("view")
    view.add_argument("name")

    create = sub.add_parser("create")
    create.add_argument("name")
    create.add_argument("--content-file", required=True)
    create.add_argument("--root")

    patch = sub.add_parser("patch")
    patch.add_argument("name")
    patch.add_argument("--file", default="SKILL.md")
    patch.add_argument("--old", required=True)
    patch.add_argument("--new", required=True)

    write = sub.add_parser("write-file")
    write.add_argument("name")
    write.add_argument("file_path")
    write.add_argument("--content-file", required=True)

    archive = sub.add_parser("archive")
    archive.add_argument("name")

    restore = sub.add_parser("restore")
    restore.add_argument("name")
    restore.add_argument("--root")

    pin = sub.add_parser("pin")
    pin.add_argument("name")

    unpin = sub.add_parser("unpin")
    unpin.add_argument("name")

    cur = sub.add_parser("curate")
    cur.add_argument("--dry-run", action="store_true", default=False)
    cur.add_argument("--apply", action="store_true", default=False)
    cur.add_argument("--stale-days", type=int, default=30)
    cur.add_argument("--archive-days", type=int, default=90)

    args = parser.parse_args()
    try:
        if args.cmd == "status":
            result = status()
        elif args.cmd == "list":
            result = list_skills()
        elif args.cmd == "usage":
            result = load_usage()
        elif args.cmd == "view":
            result = view_skill(args.name)
        elif args.cmd == "create":
            content = open(args.content_file, "r", encoding="utf-8").read()
            result = create_skill(args.name, content, root=args.root)
        elif args.cmd == "patch":
            result = patch_skill(args.name, args.old, args.new, file_path=args.file)
        elif args.cmd == "write-file":
            content = open(args.content_file, "r", encoding="utf-8").read()
            result = write_support_file(args.name, args.file_path, content)
        elif args.cmd == "archive":
            result = archive_skill(args.name)
        elif args.cmd == "restore":
            result = restore_skill(args.name, root=args.root)
        elif args.cmd == "pin":
            result = pin_skill(args.name, True)
        elif args.cmd == "unpin":
            result = pin_skill(args.name, False)
        elif args.cmd == "curate":
            dry_run = args.dry_run or not args.apply
            result = curate(dry_run=dry_run, stale_days=args.stale_days, archive_days=args.archive_days)
        else:
            raise AssertionError(args.cmd)
    except SkillStoreError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    print(json_dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

