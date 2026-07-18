# samton-plugins

## 작업 시작 규칙

작업을 시작하기 전에 `git pull`을 실행하여 리포지토리가 최신 상태인지 확인한다.

## 플러그인 배포 규칙

레거시 Claude marketplace에 등록된 플러그인을 수정한 후 커밋할 때, 다음 **두 파일의 `version` 필드를 동일한 값으로 함께** 올려야 한다:

1. `.claude-plugin/marketplace.json` 안의 해당 플러그인 entry의 `version`
2. `plugins/<plugin-name>/.codex-plugin/plugin.json`의 `version`

하나만 올리면 marketplace와 플러그인 자체 메타데이터가 어긋난다 (실제로 과거에 한쪽만 올린 미스매치가 여러 번 발생). 변경 직전 두 파일 모두 grep해서 현재 값을 확인하고, 같은 commit 안에서 함께 bump한다.

ChatGPT Work 전용 플러그인은 기존 Claude marketplace와 충돌하지 않도록 `chatgpt-work/.agents/plugins/marketplace.json`에 등록하고, 본체는 `chatgpt-work/plugins/<plugin-name>/`에 둔다. 이 현대식 marketplace entry에는 `version` 필드를 두지 않고, `chatgpt-work/plugins/<plugin-name>/.codex-plugin/plugin.json`의 버전을 단일 기준으로 사용한다. 커밋 전 marketplace의 로컬 경로와 manifest의 `name`이 일치하는지 계약 테스트로 확인한다.
