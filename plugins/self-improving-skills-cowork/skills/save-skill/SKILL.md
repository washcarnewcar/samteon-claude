---
name: save-skill
description: 학습 스킬(SKILL.md)을 사용자에게 파일로 보내 claude.ai '스킬 저장' 등록을 안내한다. 이번 세션에서 증류·수정된 스킬을 세션 종료 전에 영속화할 때, "이 스킬 저장해줘", "스킬 백업해줘", "세션 끝나기 전에 스킬 남겨줘" 등에 사용. 인자 없이 실행하면 미저장 스킬을 자동 감지한다.
---

학습 스킬을 claude.ai 에 영속화하는 Cowork 전용 흐름입니다. 이 컨테이너의 `~/.claude/skills` 는 세션 종료 시 사라지므로, '스킬 저장' 등록만이 스킬을 다음 세션으로 이어줍니다.

## 1단계 — 대상 결정

인자로 스킬 이름(들)이 주어지면 그 스킬들이 대상입니다. 인자가 없으면 **미저장 후보를 자동 감지**하세요:

```bash
python3 - <<'EOF'
import json, os
skills_dir = os.path.expanduser("~/.claude/skills")
synced = set()
try:
    with open(os.path.join(skills_dir, "manifest.json"), encoding="utf-8") as fh:
        for s in json.load(fh).get("skills", []):
            synced.add(str(s.get("skillId") or ""))
            synced.add(str(s.get("name") or ""))
except Exception:
    pass
unsaved, saved = [], []
for entry in sorted(os.listdir(skills_dir)):
    if entry.startswith("."):
        continue
    p = os.path.join(skills_dir, entry, "SKILL.md")
    if not os.path.isfile(p):
        continue
    head = open(p, encoding="utf-8", errors="ignore").read(2048)
    if "self-improving-skills" not in head and "origin: distilled" not in head:
        continue  # 학습 스킬만 대상 (plugin/anthropic 스킬 제외)
    (saved if entry in synced else unsaved).append(entry)
print("미저장(이번 세션 생성, 세션 종료 시 소실):", unsaved or "없음")
print("저장됨(claude.ai 동기화로 존재):", saved or "없음")
EOF
```

- `미저장` 목록이 기본 대상입니다.
- `저장됨` 스킬이라도 **이번 세션에서 patch 됐다면**(사용자가 언급했거나 이 대화에서 수정한 기억이 있으면) 재저장 대상에 포함하세요 — 컨테이너 안의 수정본은 저장하지 않으면 사라집니다.
- 대상이 없으면 "저장할 학습 스킬이 없습니다"라고 한 줄 보고하고 끝내세요.

## 2단계 — 예약어 사전 점검

각 대상의 frontmatter `name` 에 `claude` 또는 `anthropic` 이 들어 있으면 '스킬 저장'이 거부됩니다 (claude.ai 예약어). 저장 전에 예약어 없는 이름을 제안하고, **디렉토리명과 frontmatter name 을 함께** 변경한 뒤 진행하세요 (예: `claude-code-hook-diagnostics` → `cloud-hook-diagnostics`).

## 3단계 — 전송과 안내

1. 각 대상의 SKILL.md 를 **SendUserFile** 로 보내세요 (caption: 스킬 이름 + 무엇을 하는 스킬인지 한 줄).
2. 사용자에게 안내하세요: 파일 카드의 **'스킬 저장' 버튼**을 누르면 claude.ai 계정에 등록되고, 다음 Cowork/Claude Code 세션 컨테이너에 자동 동기화됩니다.
3. 이미 같은 이름이 등록된 스킬을 재저장한 경우: 갱신인지 중복 생성인지는 claude.ai 동작에 따르므로, 저장 후 설정 > 스킬 목록에서 중복이 생겼는지 확인하고 오래된 쪽을 삭제하도록 한 줄 덧붙이세요.
