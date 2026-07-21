from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = PLUGIN_ROOT / "skills" / "code-review" / "SKILL.md"
FEATURE_SKILL_PATH = PLUGIN_ROOT / "skills" / "feature" / "SKILL.md"
HELPER_PATH = PLUGIN_ROOT / "scripts" / "review_feedback.py"


def test_code_review_skill_uses_packaged_review_feedback_helper():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert HELPER_PATH.is_file()
    assert (
        'REVIEW_FEEDBACK_HELPER="${CLAUDE_PLUGIN_ROOT}/scripts/review_feedback.py"'
        in skill
    )


def test_code_review_skill_reserves_reviewer_launches_before_background_jobs():
    skill = SKILL_PATH.read_text(encoding="utf-8")
    phase_four = skill.split("### Phase 4: Launch Reviewers", 1)[1].split(
        "**Reviewer A focus text", 1
    )[0]

    assert phase_four.index("--action reserve-launches") < phase_four.index("Bash(")
    assert "--attempt <reserved-attempt> --job-id <id>" in phase_four
    assert "`reconcile-launches`" in phase_four


def test_review_skills_document_runtime_and_complete_recovery_contracts():
    review_skill = SKILL_PATH.read_text(encoding="utf-8")
    feature_skill = FEATURE_SKILL_PATH.read_text(encoding="utf-8")

    assert "Python 3.9+" in feature_skill
    assert "status: complete" in review_skill
    assert "`resume`이 `persist-feedback`을 반환하는 상태도 허용" in review_skill
    assert "`.candidate`, `.original`, `.rollback` 조합" in review_skill
    assert "`.rollback` 경로로 atomic no-replace 이동" in review_skill
