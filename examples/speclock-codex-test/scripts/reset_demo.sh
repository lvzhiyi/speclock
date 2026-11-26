#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

rm -rf .speclock
git checkout -- .
git clean -fd

git status -sb
echo "Reset to initial recording state; ready to start a new Codex session."
