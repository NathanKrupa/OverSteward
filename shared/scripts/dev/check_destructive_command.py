#!/usr/bin/env python3
# ABOUTME: PreToolUse(Bash) guard — hard-deny hook evasion; ask before destructive commands.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/.claude/hooks/.
"""Two-tier PreToolUse(Bash) guard for destructive and hook-evasion commands.

Two decision classes, checked in this priority order:

1. **Hook-evasion / secret-staging (``deny`` — hard block).** Estate invariant
   I-3: an agent NEVER bypasses git hooks and NEVER blind-stages the tree.
   ``git ... --no-verify``, ``git ... --no-gpg-sign``, ``--admin`` (gh/git),
   ``core.hooksPath`` pointed at ``/dev/null`` or emptied, ``git add -A`` /
   ``git add .``, and staging a real secret file (``git add`` of
   ``.env*`` / ``*.pem`` / ``*.key`` / ``credentials*``). These are never
   legitimate for a dispatch agent, so they are hard-denied — NOT downgradable
   to an ask. This class is checked FIRST so a destructive-pattern match can
   never soften the decision to ``ask``. Placeholder dotenv files
   (``.env.example`` / ``.env.sample`` / ``.env.template`` / ``.env.dist``)
   carry no real values and are legitimately committed — they are carved out.

2. **Destructive-but-sometimes-legitimate (``ask`` — confirm gate).**
   Encodes the pattern table of ``shared/skills/careful.md``: file-system

Encodes the pattern table of ``shared/skills/careful.md``: file-system
destruction (``rm -rf`` on non-artifacts, ``shred``/``wipe``), hard-to-reverse
git (``push --force``, ``reset --hard``, ``clean -fd``, ``branch -D``,
whole-tree discard, rebase), destructive SQL (``DROP``/``TRUNCATE``/``DELETE``
without ``WHERE``, ``manage.py flush``), container/infra teardown
(``docker system prune -a``, ``docker volume rm``, ``kubectl delete``), and
package-management footguns (``pip install`` outside a venv, ``npm install
-g``).

On a class-2 match the hook does NOT hard-deny — ``careful.md`` is a confirm
gate, not a wall. It emits an ``ask`` permission decision on stdout with a
structured risk explanation. Claude Code surfaces that as a confirmation prompt:
in an interactive session Nathan approves or rejects; in an autonomous/operator
context an unanswered ``ask`` blocks the command. Both match the intent.

``careful.md``'s Safe Exceptions (``rm -rf node_modules|dist|build|...``,
``git stash``, ``git branch -d``, ``docker system prune`` without ``-a``) pass
through cleanly — exit 0, no prompt.

Command detection is anchored at a shell-command position (start of line or
after a ``; & |`` separator, allowing a leading run of ``VAR=value`` env
assignments) so quoted mentions in ``echo``/``printf``/test data do not
false-positive. This mirrors ``guard_main_worktree.py``'s anchoring after the
#172 bypass fix.

Decision logic is split into pure functions so it is unit-tested without a
shell. This is an estate-canonical byte-copy (ratchet treaty): improve here and
redeploy; never edit the ``.claude/hooks/`` copy in isolation.
"""

from __future__ import annotations

import json
import re
import sys

# ---------------------------------------------------------------------------
# Command-position anchoring (shared with guard_main_worktree.py post-#172).
# A command sits at start-of-line or after a shell separator, optionally
# preceded by a run of ``VAR=value`` env assignments. Anchoring here — rather
# than matching a bare substring — is what keeps quoted mentions (``echo "rm
# -rf /"``) and test data from false-positiving.
# ---------------------------------------------------------------------------
_SEP = r"(?:^|[\n;&|])\s*"  # start-of-line or after a shell separator
_ASSIGN = r"(?:\w+=\S+\s+)*"  # a leading run of ``VAR=value`` env assignments
_AT_CMD = _SEP + _ASSIGN

# Build-artifact directories that ``rm -rf`` may target without a prompt
# (careful.md Safe Exceptions). Matched as whole path segments so a stray
# ``rm -rf build_prod_data`` is NOT treated as the safe ``build``.
_SAFE_RM_TARGETS = (
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
)
# ``*.egg-info`` is a glob rather than a fixed name.
_SAFE_EGG_INFO = re.compile(r"(?:^|[\s/])[\w.-]*\.egg-info/?\s*$")


def _rm_targets(command: str) -> list[str]:
    """Return the non-flag arguments of a leading ``rm`` command, or []."""
    m = re.search(_AT_CMD + r"rm\b(?P<args>[^\n;&|]*)", command)
    if not m:
        return []
    args = m.group("args").split()
    return [a for a in args if not a.startswith("-")]


def _all_safe_rm_targets(command: str) -> bool:
    """True if every ``rm`` target is a recognized build artifact.

    An ``rm`` with no explicit target (e.g. a bare glob resolved by the shell)
    is not classifiable as safe here — callers only reach this after deciding a
    prompt is otherwise warranted, so unknown → not-safe (fall through to ask).
    """
    targets = _rm_targets(command)
    if not targets:
        return False
    for t in targets:
        stripped = t.rstrip("/")
        if stripped.startswith("./"):
            stripped = stripped[2:]
        if stripped in _SAFE_RM_TARGETS:
            continue
        if _SAFE_EGG_INFO.search(t):
            continue
        return False
    return True


# ---------------------------------------------------------------------------
# Destructive pattern detectors. Each entry is (category, regex, risk phrase).
# Detectors are checked in order; the FIRST match wins the prompt so the risk
# message names the most specific concern.
# ---------------------------------------------------------------------------

# File system --------------------------------------------------------------
# A combined short flag carrying BOTH r/R and f (``-rf``, ``-fr``, ``-Rf``), or
# the two given separately (``-r -f``). ``[rR]`` and ``f`` in one ``-xxx`` token.
_RM_RF = re.compile(
    _AT_CMD + r"rm\s+(?:-\w*[rR]\w*f\w*\b|-\w*f\w*[rR]\w*\b|-[rR]\b[^\n;&|]*\s-\w*f)"
)
# Recursive without force (``rm -r``/``-R``) — a still-destructive tree delete.
_RM_R = re.compile(_AT_CMD + r"rm\s+-\w*[rR]\w*\b")
_RM_GLOB = re.compile(_AT_CMD + r"rm\b[^\n;&|]*\*")
_SHRED = re.compile(_AT_CMD + r"(?:shred|wipe)\b")

# Git — hard to reverse ----------------------------------------------------
_GIT_PUSH_FORCE = re.compile(_AT_CMD + r"git\s+push\b[^\n;&|]*(?:--force(?!-with-lease)\b|(?<!\w)-f\b)")
_GIT_RESET_HARD = re.compile(_AT_CMD + r"git\s+reset\b[^\n;&|]*--hard\b")
_GIT_CLEAN = re.compile(_AT_CMD + r"git\s+clean\b[^\n;&|]*-\w*f")
_GIT_BRANCH_FORCE = re.compile(_AT_CMD + r"git\s+branch\b[^\n;&|]*(?<!\w)-D\b")
_GIT_DISCARD_ALL = re.compile(
    _AT_CMD + r"git\s+(?:checkout|restore)\b[^\n;&|]*?(?:--\s+\.|\s\.)\s*(?:$|[;&|])"
)
_GIT_REBASE = re.compile(_AT_CMD + r"git\s+rebase\b")

# Database -----------------------------------------------------------------
# A pure text search/print tool at command position (``grep``, ``rg``, ``cat``,
# ``head`` ...) treats SQL keywords as DATA, not a statement to run. When such a
# tool leads the command and NO database client verb appears, the SQL detectors
# stand down (a ``grep 'DROP TABLE' migrations/`` is not a destructive op).
_TEXT_TOOL_LEAD = re.compile(
    _AT_CMD + r"(?:grep|egrep|fgrep|rg|ack|cat|less|more|head|tail|awk|sed|echo|printf)\b"
)
_DB_CLIENT = re.compile(
    r"(?:^|[\s;&|])(?:psql|mysql|sqlite3?|mongo|redis-cli|clickhouse-client|"
    r"cockroach\s+sql|dbshell|db\s+scratch|db_scratch|manage\.py\s+dbshell|alembic)\b"
)


def _is_sql_data_only(command: str) -> bool:
    """True if SQL keywords here are inert data (text tool, no DB client)."""
    return bool(_TEXT_TOOL_LEAD.search(command)) and not _DB_CLIENT.search(command)


_SQL_DROP_TRUNCATE = re.compile(r"\b(?:DROP\s+(?:TABLE|DATABASE)|TRUNCATE)\b", re.IGNORECASE)
_SQL_DELETE_NO_WHERE = re.compile(
    r"\bDELETE\s+FROM\s+[\w.\"'`]+\s*(?:;|$)", re.IGNORECASE
)
_MANAGE_FLUSH = re.compile(_AT_CMD + r"(?:python[0-9.]*\s+)?(?:\S*)?manage\.py\s+flush\b")

# Container / infrastructure ----------------------------------------------
_DOCKER_PRUNE_ALL = re.compile(_AT_CMD + r"docker\s+system\s+prune\b[^\n;&|]*-\w*a")
_DOCKER_VOLUME_RM = re.compile(_AT_CMD + r"docker\s+volume\s+rm\b")
_KUBECTL_DELETE = re.compile(_AT_CMD + r"kubectl\s+delete\b")

# Package management -------------------------------------------------------
_NPM_INSTALL_GLOBAL = re.compile(
    _AT_CMD + r"npm\s+(?:install|i)\b[^\n;&|]*(?:(?<!\w)-g\b|--global\b)"
)
_PIP_INSTALL = re.compile(_AT_CMD + r"(?:python[0-9.]*\s+-m\s+)?pip[0-9.]*\s+install\b")


def _sql_delete_without_where(command: str) -> bool:
    """True if a ``DELETE FROM <table>`` has no ``WHERE`` clause before its end."""
    for m in re.finditer(r"\bDELETE\s+FROM\s+[\w.\"'`]+", command, re.IGNORECASE):
        tail = command[m.end():]
        # The statement ends at the next ``;`` (or end of string).
        stmt_end = tail.find(";")
        stmt = tail if stmt_end == -1 else tail[:stmt_end]
        if not re.search(r"\bWHERE\b", stmt, re.IGNORECASE):
            return True
    return False


def _pip_outside_venv(command: str) -> bool:
    """True if a ``pip install`` runs and no venv marker is present.

    careful.md flags ``pip install`` OUTSIDE a virtual environment. We treat an
    explicit venv-qualified invocation (``uv pip install``, ``.venv/bin/pip``,
    ``python -m pip`` inside an activated venv marker, ``pipx``) as in-scope of a
    venv and pass it through. Heuristic and conservative: when unsure, ask.
    """
    if not _PIP_INSTALL.search(command):
        return False
    # Qualified paths / tools that imply an isolated environment.
    if re.search(r"(?:\.?venv|virtualenv|env)/bin/pip", command):
        return False
    if re.search(r"(?:^|[\s;&|])(?:uv|pipx|poetry|pdm|hatch)\s+", command):
        return False
    if "--user" in command:
        return False
    return True


# Each rule's detector is a predicate over the command string alone. Regex-only
# detectors are built by ``_matches(pattern)``, which closes over the compiled
# regex; the two detectors that need extra context (rm's safe-artifact
# exemption, the SQL data-vs-execution distinction) are named predicates that
# also close over their regex. This keeps the rule table one column narrower and
# every predicate a uniform ``str -> bool``.
def _matches(pattern: re.Pattern[str]) -> "object":
    """Build a command-only predicate that fires when ``pattern`` matches."""
    return lambda command: bool(pattern.search(command))


def _rm_destructive(command: str) -> bool:
    """An ``rm -rf`` match that is NOT confined to build artifacts."""
    return bool(_RM_RF.search(command)) and not _all_safe_rm_targets(command)


def _rm_r_destructive(command: str) -> bool:
    """An ``rm -r`` match that is NOT confined to build artifacts."""
    return bool(_RM_R.search(command)) and not _all_safe_rm_targets(command)


def _drop_truncate_exec(command: str) -> bool:
    """A DROP/TRUNCATE actually executed (not searched/printed as text)."""
    return bool(_SQL_DROP_TRUNCATE.search(command)) and not _is_sql_data_only(command)


def _delete_no_where(command: str) -> bool:
    """A ``DELETE FROM`` with no ``WHERE`` clause, executed (not inert text)."""
    return _sql_delete_without_where(command) and not _is_sql_data_only(command)


# The rule table, in priority order — the FIRST matching rule wins the prompt so
# the risk message names the most specific concern. Each row is
# ``(category, predicate, risk)``. careful.md's pattern table maps 1:1 here.
_RULES: tuple[tuple[str, object, str], ...] = (
    # File system
    ("rm -rf", _rm_destructive,
     "recursively force-deletes files that are not recognized build artifacts"),
    ("shred/wipe", _matches(_SHRED), "securely and irreversibly destroys file data"),
    ("rm -r", _rm_r_destructive, "recursively deletes a directory tree"),
    ("rm glob", _matches(_RM_GLOB),
     "deletes files matched by a glob — potentially many, unreviewed"),
    # Git — hard to reverse
    ("git push --force", _matches(_GIT_PUSH_FORCE),
     "overwrites remote history and can clobber others' commits"),
    ("git reset --hard", _matches(_GIT_RESET_HARD),
     "discards all uncommitted changes and moves the branch pointer"),
    ("git clean -f", _matches(_GIT_CLEAN),
     "permanently deletes untracked files (drafts, notes, artifacts)"),
    ("git branch -D", _matches(_GIT_BRANCH_FORCE),
     "force-deletes a branch even if it holds unmerged commits"),
    ("git checkout/restore .", _matches(_GIT_DISCARD_ALL), "discards ALL working-tree changes"),
    ("git rebase", _matches(_GIT_REBASE),
     "rewrites commit history — dangerous on a shared branch"),
    # Database
    ("DROP/TRUNCATE", _drop_truncate_exec,
     "drops or truncates a table or database — irreversible data loss"),
    ("DELETE without WHERE", _delete_no_where, "deletes every row in the table"),
    ("manage.py flush", _matches(_MANAGE_FLUSH), "deletes all data from the database"),
    # Container / infrastructure
    ("docker system prune -a", _matches(_DOCKER_PRUNE_ALL),
     "removes all unused images, not just dangling ones"),
    ("docker volume rm", _matches(_DOCKER_VOLUME_RM),
     "destroys a data volume — persisted data is lost"),
    ("kubectl delete", _matches(_KUBECTL_DELETE), "tears down a live cluster resource"),
    # Package management
    ("npm install -g", _matches(_NPM_INSTALL_GLOBAL),
     "installs a project tool globally, polluting the system environment"),
    ("pip install outside a venv", _pip_outside_venv,
     "installs into the system/base Python instead of a virtual environment"),
)


def _match(command: str) -> tuple[str, str] | None:
    """Return (category, risk) for the first destructive pattern matched."""
    for category, predicate, risk in _RULES:
        if predicate(command):  # type: ignore[operator]
            return (category, risk)
    return None


# ---------------------------------------------------------------------------
# Class 1 — git-hook-evasion / secret-staging detectors (hard ``deny``).
#
# Estate invariant I-3: a dispatch agent NEVER bypasses git hooks and NEVER
# blind-stages the working tree. Every shape below is unambiguously an evasion
# — there is no legitimate agent use — so it is hard-denied rather than gated
# with an ``ask``. These are checked BEFORE the class-2 destructive rules so a
# destructive-pattern match can never downgrade the decision to ``ask``.
# ---------------------------------------------------------------------------

# ``--no-verify`` / ``-n`` on commit skips the pre-commit/commit-msg hooks;
# ``--no-gpg-sign`` skips signing. Anchored to a leading ``git``.
_GIT_NO_VERIFY = re.compile(_AT_CMD + r"git\b[^\n;&|]*\s--no-verify\b")
_GIT_NO_GPG_SIGN = re.compile(_AT_CMD + r"git\b[^\n;&|]*\s--no-gpg-sign\b")
# ``--admin`` on ``gh pr merge`` (or git) bypasses branch-protection/CI gates.
_ADMIN_FLAG = re.compile(_AT_CMD + r"(?:gh|git)\b[^\n;&|]*\s--admin\b")
# ``core.hooksPath`` redirected to /dev/null or emptied disables all hooks.
# Matches ``git ... -c core.hooksPath=/dev/null`` and ``git config
# core.hooksPath ''`` (value = /dev/null, empty string, or nothing).
_HOOKSPATH_NEUTERED = re.compile(
    r"core\.hooksPath\s*(?:=|\s)\s*(?P<val>/dev/null\b|''|\"\"|(?=[\s;&|]|$))",
    re.IGNORECASE,
)
# ``git add -A`` / ``git add --all`` / ``git add .`` — blind whole-tree staging.
_GIT_ADD_ALL = re.compile(
    _AT_CMD + r"git\s+add\b[^\n;&|]*(?:(?<!\w)-A\b|--all\b|(?<!\S)\.(?=\s|$|[;&|]))"
)

# Secret files that must never be staged. A placeholder dotenv (``.env.example``
# and friends) carries no real values and is legitimately committed — carved
# out below so only real secret files trip the guard.
_SECRET_PLACEHOLDER_SUFFIXES = (".example", ".sample", ".template", ".dist")
# A single ``git add`` argument that names a secret file. ``.env`` and any
# ``.env.<x>`` variant, plus ``*.pem`` / ``*.key`` / ``credentials*``.
_SECRET_ARG = re.compile(
    r"(?:^|/)(?:\.env(?:\.[\w.-]+)?|[\w.-]*\.pem|[\w.-]*\.key|credentials[\w.-]*)$"
)
_GIT_ADD_LEAD = re.compile(_AT_CMD + r"git\s+add\b(?P<args>[^\n;&|]*)")


def _is_placeholder_dotenv(arg: str) -> bool:
    """True for ``.env.example`` / ``.sample`` / ``.template`` / ``.dist``."""
    base = arg.rsplit("/", 1)[-1]
    return any(base.endswith(sfx) for sfx in _SECRET_PLACEHOLDER_SUFFIXES)


def _stages_secret_file(command: str) -> bool:
    """True if a ``git add`` names a real secret file (placeholders exempt)."""
    m = _GIT_ADD_LEAD.search(command)
    if not m:
        return False
    for arg in m.group("args").split():
        if arg.startswith("-"):
            continue
        if _SECRET_ARG.search(arg) and not _is_placeholder_dotenv(arg):
            return True
    return False


# Evasion rule table, in priority order. Each row is ``(category, predicate,
# reason)`` where ``reason`` completes "This ..." in the deny message.
_EVASION_RULES: tuple[tuple[str, object, str], ...] = (
    ("git --no-verify", _matches(_GIT_NO_VERIFY),
     "bypasses the pre-commit / commit-msg hooks that guard every commit"),
    ("git --no-gpg-sign", _matches(_GIT_NO_GPG_SIGN),
     "skips commit signing, defeating provenance verification"),
    ("--admin bypass", _matches(_ADMIN_FLAG),
     "bypasses branch-protection and required-check gates"),
    ("core.hooksPath disabled", _matches(_HOOKSPATH_NEUTERED),
     "redirects git's hooks path to nothing, disabling all repository hooks"),
    ("git add -A / .", _matches(_GIT_ADD_ALL),
     "blind-stages the entire working tree instead of explicit paths"),
    ("git add of a secret file", _stages_secret_file,
     "stages a secret file (.env / *.pem / *.key / credentials*) into a commit"),
)


def _match_hook_evasion(command: str) -> tuple[str, str] | None:
    """Return (category, reason) for the first hook-evasion pattern matched."""
    for category, predicate, reason in _EVASION_RULES:
        if predicate(command):  # type: ignore[operator]
            return (category, reason)
    return None


def _deny_message(category: str, reason: str, command: str) -> str:
    """Human-readable hard-block explanation surfaced with the deny decision."""
    return (
        "HOOK-EVASION / SECRET-STAGING — hard blocked (estate invariant I-3)\n\n"
        f"Command: {command.strip()}\n"
        f"Pattern: {category}\n"
        f"Reason: This {reason}.\n\n"
        "I-3: a dispatch agent never bypasses git hooks and never blind-stages "
        "the tree. This is not an ask you can approve — remove the bypass flag "
        "and stage explicit, non-secret paths instead."
    )


def _emit_deny(reason: str) -> None:
    """Emit a ``deny`` PreToolUse permission decision on stdout and exit 0."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(output))
    sys.exit(0)


def _ask_message(category: str, risk: str, command: str) -> str:
    """Human-readable risk explanation surfaced with the ask prompt."""
    return (
        "DESTRUCTIVE COMMAND — confirmation required\n\n"
        f"Command: {command.strip()}\n"
        f"Pattern: {category}\n"
        f"Risk: This {risk}.\n\n"
        "careful.md is a confirm gate: review the command and approve only if "
        "the destruction is intended. Safe alternatives or a narrower scope are "
        "often available. Full rule: shared/skills/careful.md"
    )


def _emit_ask(reason: str) -> None:
    """Emit an ``ask`` PreToolUse permission decision on stdout and exit 0."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(output))
    sys.exit(0)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0  # unparseable input → do not block
    if not isinstance(event, dict):
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = (event.get("tool_input") or {}).get("command", "") or ""
    if not command:
        return 0

    # Class 1 first — hook evasion is a hard ``deny`` and must never be
    # downgradable to a class-2 ``ask``.
    evasion = _match_hook_evasion(command)
    if evasion is not None:
        category, reason = evasion
        _emit_deny(_deny_message(category, reason, command))
        return 0  # _emit_deny exits; unreachable, kept for type clarity

    hit = _match(command)
    if hit is None:
        return 0
    category, risk = hit
    _emit_ask(_ask_message(category, risk, command))
    return 0  # _emit_ask exits; unreachable, kept for type clarity


if __name__ == "__main__":
    sys.exit(main())
