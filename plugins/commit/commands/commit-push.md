---
allowed-tools: Bash(git add:*), Bash(git status:*), Bash(git commit:*), Bash(git push:*)
description: Commit and push to remote
---

## Context

- Current git status: !`git status`
- Current git diff (staged and unstaged changes): !`git diff HEAD`
- Current branch: !`git branch --show-current`
- Recent commits: !`git log --oneline -10`

## Your task

Based on the above changes:

1. Create a single commit with an appropriate message
2. Push the commit to the remote repository

You have the capability to call multiple tools in a single response. Stage, commit, and push using a single message.
Do not use any other tools or do anything else. Do not send any other text or messages besides these tool calls.
