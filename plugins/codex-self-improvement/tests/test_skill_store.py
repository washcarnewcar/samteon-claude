import datetime
import importlib
import os
import sys

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, SCRIPTS_DIR)


def _skill(root, name, extra_frontmatter=""):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "---\nname: {0}\ndescription: test skill\n{1}---\nbody\n".format(
            name, extra_frontmatter
        ),
        encoding="utf-8",
    )
    return d


def _iso_days_ago(days):
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(days=days)).isoformat()


def _store(tmp_path, monkeypatch, *roots):
    monkeypatch.setenv("PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CODEX_SELF_IMPROVE_SKILL_ROOTS", os.pathsep.join(str(r) for r in roots))
    monkeypatch.setenv("CODEX_SELF_IMPROVE_CREATE_ROOT", str(roots[0]))
    import skill_store

    return importlib.reload(skill_store)


def test_default_create_root_is_codex_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("CODEX_SELF_IMPROVE_SKILL_ROOTS", raising=False)
    monkeypatch.delenv("CODEX_SELF_IMPROVE_CREATE_ROOT", raising=False)
    import skill_store

    store = importlib.reload(skill_store)
    content = "---\nname: codex-born\ndescription: created in the Codex skill root\n---\nbody\n"
    result = store.create_skill("codex-born", content)

    expected = tmp_path / ".codex" / "skills" / "codex-born"
    assert result["path"] == str(expected.resolve())
    assert (expected / "SKILL.md").is_file()


def test_curate_protects_untracked_user_skills_and_skips_system_root(tmp_path, monkeypatch):
    agents = tmp_path / ".agents" / "skills"
    codex = tmp_path / ".codex" / "skills"
    _skill(agents, "handmade")
    _skill(codex / ".system", "bundled")
    store = _store(tmp_path, monkeypatch, agents, codex)

    listed = store.list_skills()["skills"]
    assert [row["name"] for row in listed] == ["handmade"]

    result = store.curate(dry_run=True, stale_days=0, archive_days=0)
    row = result["candidates"][0]
    assert row["name"] == "handmade"
    assert row["candidate_action"] == "keep"
    assert row["created_by"] == "user"
    assert "protected user" in row["reason"]


def test_agent_archive_candidates_and_proven_usage_threshold(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    _skill(root, "unproven")
    _skill(root, "proven")
    store = _store(tmp_path, monkeypatch, root)

    store.record_usage("unproven", created_by="agent")
    store.record_usage("proven", created_by="agent")

    with store.usage_lock():
        usage = store.load_usage()
        usage["skills"]["unproven"].update(
            created_at=_iso_days_ago(121), last_used_at=_iso_days_ago(120), use_count=2
        )
        usage["skills"]["proven"].update(
            created_at=_iso_days_ago(121), last_used_at=_iso_days_ago(120), use_count=3
        )
        store.save_usage(usage)

    rows = {row["name"]: row for row in store.curate(dry_run=True)["candidates"]}
    assert rows["unproven"]["candidate_action"] == "archive"
    assert rows["proven"]["candidate_action"] == "mark_stale"


def test_record_usage_reactivates_stale_skill(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    _skill(root, "reactive")
    store = _store(tmp_path, monkeypatch, root)
    store.record_usage("reactive", created_by="agent")
    with store.usage_lock():
        usage = store.load_usage()
        usage["skills"]["reactive"]["state"] = "stale"
        store.save_usage(usage)

    store.record_usage("reactive", use=True)
    assert store.load_usage()["skills"]["reactive"]["state"] == "active"


def test_frontmatter_pin_blocks_archive_candidate(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    _skill(root, "pinned", extra_frontmatter="pinned: true\n")
    store = _store(tmp_path, monkeypatch, root)
    store.record_usage("pinned", created_by="agent")
    with store.usage_lock():
        usage = store.load_usage()
        usage["skills"]["pinned"]["created_at"] = _iso_days_ago(201)
        usage["skills"]["pinned"]["last_used_at"] = _iso_days_ago(200)
        store.save_usage(usage)

    row = store.curate(dry_run=True)["candidates"][0]
    assert row["candidate_action"] == "keep"
    assert row["pinned"] is True
