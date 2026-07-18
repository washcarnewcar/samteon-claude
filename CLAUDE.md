# samton-plugins

## 작업 시작 규칙

작업을 시작하기 전에 `git pull`을 실행하여 리포지토리가 최신 상태인지 확인한다.

## 플러그인 배포 규칙

Claude 플러그인을 수정한 후 커밋할 때, 다음 **두 파일의 `version` 필드를 동일한 값으로 함께** 올려야 한다:

1. `.claude-plugin/marketplace.json` 안의 해당 플러그인 entry의 `version`
2. `plugins/<plugin-name>/.claude-plugin/plugin.json`의 `version`

하나만 올리면 marketplace와 플러그인 자체 메타데이터가 어긋난다 (실제로 과거에 한쪽만 올린 미스매치가 여러 번 발생). 변경 직전 두 파일 모두 grep해서 현재 값을 확인하고, 같은 commit 안에서 함께 bump한다.
