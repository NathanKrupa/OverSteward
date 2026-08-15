ABOUTME: PreToolUse safety skill that warns before destructive shell commands.
ABOUTME: Adapted from garrytan/gstack's /careful pattern for House of Krupa contexts.

# Careful — Destructive Command Guard

Intercept and warn before executing shell commands that are destructive, hard to reverse, or affect shared state.

## When This Skill Is Active

This skill should be activated (via hook or manual invocation) when working in any repository where destructive operations could cause data loss or affect shared infrastructure.

## Destructive Command Patterns

Before executing any Bash command, check whether it matches these patterns. If it does, **STOP and ask Nathan for confirmation** before proceeding. Explain exactly what the command will do and what data could be affected.

### File System Destruction
- `rm -rf` (except on build artifacts: node_modules, dist, build, __pycache__, .pytest_cache, *.egg-info)
- `rm -r` on directories outside the current project
- Any `rm` targeting more than 5 files via glob
- `shred`, `wipe`, or secure-delete commands

### Git — Hard to Reverse
- `git push --force` or `git push -f` (especially to main/master)
- `git reset --hard`
- `git clean -fd` or `git clean -fx`
- `git branch -D` (force-delete)
- `git checkout -- .` or `git restore .` (discards all changes)
- `git rebase` on shared branches

### Database
- `DROP TABLE`, `DROP DATABASE`, `TRUNCATE`, `DELETE FROM` without WHERE clause
- Any raw SQL that modifies schema in production
- `python manage.py flush`

### Container / Infrastructure
- `docker system prune -a`
- `docker volume rm`
- `kubectl delete` (namespace, deployment, service, pod)
- Any command targeting production environment variables or secrets

### Package Management
- `pip install` outside a virtual environment
- `conda install` in the base environment
- `npm install -g` for project-specific tools

## Safe Exceptions

These are always safe and do NOT require confirmation:
- `rm -rf node_modules` / `rm -rf dist` / `rm -rf build` / `rm -rf __pycache__`
- `rm -rf .pytest_cache` / `rm -rf *.egg-info` / `rm -rf .mypy_cache`
- `git stash` (reversible)
- `git branch -d` (safe delete — only works if merged)
- `docker system prune` without `-a` flag

## Response Format

When a destructive command is detected:

```
⚠️ DESTRUCTIVE COMMAND DETECTED

Command: [the command]
Risk: [what could be lost or broken]
Reversible: [yes/no/partially]

Proceed? (Confirm before I execute this)
```

## Integration Note

This skill can be enforced via a PreToolUse hook in settings.json. See the OverSteward idea store for the hook-based implementation plan.
