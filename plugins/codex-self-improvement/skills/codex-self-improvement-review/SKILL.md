---
name: codex-self-improvement-review
description: Review a completed Codex turn for durable skill improvements, using the codex-self-improvement plugin's skill-manager tools or scripts. Use after user corrections, repeated workflow friction, non-trivial debugging techniques, or when the Stop hook requests a self-improvement pass.
---

# Codex Self-Improvement Review

Use this skill to decide whether a recent interaction should update Codex's reusable skills. Treat skills as procedural memory: they record how to do a class of task, not one-off facts.

## Review Policy

1. Inspect the current thread evidence before writing anything.
2. Prefer patching an existing relevant skill over creating a new narrow skill.
3. Create a new skill only when the learning is class-level and likely to recur.
4. Put session-specific details in `references/`, reusable starters in `templates/`, and deterministic helpers in `scripts/`.
5. Capture user corrections about workflow, tone, formatting, or verification in the skill that governs that class of task.
6. Do not encode transient setup failures, missing binaries, one-off paths, temporary outages, or negative claims like "tool X does not work".
7. Never edit bundled/system/admin skills. Work in user or repo skill roots only.
8. Keep changes small, make a backup first, and report the diff summary.

## Tooling

Prefer the plugin MCP tools when available:

- `codex_skill_list`
- `codex_skill_view`
- `codex_skill_create`
- `codex_skill_patch`
- `codex_skill_write_file`
- `codex_skill_archive`
- `codex_skill_curate`
- `codex_self_improvement_status`

If the MCP server is not active, run the local helper script from this plugin:

```bash
python3 ../../scripts/skill_manager_cli.py status
python3 ../../scripts/skill_manager_cli.py list
python3 ../../scripts/skill_manager_cli.py curate --dry-run
```

Resolve script paths relative to this `SKILL.md` location.

## Output

If no durable improvement exists, say so briefly. If you changed a skill, report:

- skill name
- action taken
- backup id
- short reason

