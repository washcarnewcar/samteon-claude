# Codex Self Improvement

This plugin implements a Hermes-inspired learning loop for Codex:

- `PostToolUse` records tool telemetry.
- `Stop` can optionally request a self-improvement continuation.
- `SessionStart` injects a tiny status note.
- Skills guide review and curator workflows.
- A local MCP/CLI skill manager creates backups, tracks usage, pins important skills, archives stale skills, and restores archived skills.

The default Stop hook is conservative. It records review signals but only auto-continues when enabled with:

```bash
export CODEX_SELF_IMPROVE_AUTO=1
```

State is stored in `PLUGIN_DATA` when Codex provides it, otherwise under `~/.codex-self-improvement`.

By default, new skills created through the manager are written to `~/.codex/skills`. The manager can also read existing user skills from `~/.agents/skills` for compatibility, and `CODEX_SELF_IMPROVE_CREATE_ROOT` can override the create location.
