#!/usr/bin/env bash
# ABOUTME: Point git at .githooks/ so commit-time gates travel with the repo.
# ABOUTME: Run once per clone; session worktrees inherit the setting automatically.
#
# `pre-commit install` writes into `.git/hooks/` (or, in a worktree,
# `.git/worktrees/<name>/hooks/`) — per-checkout state that a fresh
# `git worktree add` does not carry, so the gate silently goes missing.
# The hooks-path setting is per-repo and worktrees DO inherit it, which is
# why the shim lives in `.githooks/` instead.
#
# Mirrors aigranthelper's and grantspider's `make hooks` target; OverSteward
# has no Makefile, so it is a script under the same `scripts/dev/` roof as
# new-session.sh and with_test_env.py.

set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "$root"

git config core.hooksPath .githooks
chmod +x .githooks/pre-commit

echo "✓ hooks installed — git will run .githooks/pre-commit"
echo "  gates: gaudi (architectural errors, changed files) + secret-scan"
echo "  the shim no-ops with a message when pre-commit is not on PATH"
