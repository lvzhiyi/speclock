#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

rm -rf .speclock
git checkout -- .
git clean -fd

git status -sb
echo "已复位到录屏初始状态，可直接在 Codex 新开会话重录"
