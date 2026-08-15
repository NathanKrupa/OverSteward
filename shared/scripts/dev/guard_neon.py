#!/usr/bin/env python3
# ABOUTME: PreToolUse(Bash) guard — deny every non-read-only Neon CLI command (agents get read-only Neon).
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/.claude/hooks/.
"""Allowlist (deny-by-default) guard for the Neon CLI (``neon`` / ``neonctl``).

Nathan-law (2026-07-03): **agents get READ-ONLY Neon; every mutating,
destructive, or credential-revealing Neon op is operator-only.** The estate has
a documented history of accidental full-database destruction (the 2026-04-30
``RunSQL`` router-gap wipe; the ``alembic/env.py`` parent-walk that resolves a
worktree to *prod* ``neondb``). A native ``neon`` CLI is now installed and
authenticated in WSL, exposing ``branches delete``, ``branches reset/restore``,
``projects delete``, ``databases delete``, and ``connection-string`` (credential
leak). That is too much power to leave in an agent's hands.

This is a hard ``deny`` (not an ``ask``): it emits a PreToolUse ``deny``
permission decision naming the reason and telling the operator to run the
command themselves via ``! neon ...``.

**Policy — allowlist, deny-by-default.** Only these read-only invocations pass:

- ``neon`` / ``neon --version`` / ``neon --help`` (and ``neon <cmd> --help``)
- ``neon me``
- ``neon projects list|get``
- ``neon branches list|get``
- ``neon databases list``
- ``neon roles list``
- ``neon operations list|get``

Everything else — every ``create|delete|reset|restore|update|set|rename|add|
remove|recover`` subcommand, ``connection-string``/``cs``, ``sql``/``psql``,
``--reveal`` / password flags, and any *unrecognized* subcommand — is DENIED.
Deny-by-default means a future destructive subcommand is blocked without a code
change. The read verbs and the noun aliases (``branch``, ``db``, ``role`` …) are
the CLI's own; unknown nouns fall through to deny.

**Robustness (security-critical).**

- The invoked binary is matched only at a **command position** — start of line,
  after a shell separator (``; & | && || newline``), inside command
  substitution (``$(...)`` / backticks), optionally preceded by env assignments
  and an absolute/relative path prefix (``/usr/bin/neon``). A bare substring
  ``neon`` inside a quoted string, a path argument, or a name like
  ``neon-tools`` does NOT false-positive.
- **Chaining / compounding:** every neon invocation in the command is
  classified; if ANY segment is disallowed the WHOLE command is denied. A
  destructive neon call hidden after ``&&``, ``;``, ``|``, or inside ``$(...)``
  cannot ride in on an allowed one.
- Both ``neon`` and ``neonctl`` are covered.
- The allowlist match is deliberately strict: a mutating verb can never occupy
  the read-verb slot while producing an actual mutation, so false-DENY (operator
  runs it themselves) is the only failure mode — never false-ALLOW.

Decision logic is split into pure functions so it is unit-tested without a
shell. This is an estate-canonical byte-copy (ratchet treaty): improve here and
redeploy; never edit the ``.claude/hooks/`` copy in isolation.
"""

from __future__ import annotations

import json
import re
import sys

# ---------------------------------------------------------------------------
# Command-position anchoring. A neon invocation sits at start-of-line or after
# a shell separator / command-substitution opener (``; & | ( `` backtick),
# optionally preceded by a run of ``VAR=value`` env assignments and an
# absolute/relative path prefix (``/usr/bin/neon``, ``./neon``). The binary
# token must be followed by whitespace, end-of-command, or a separator — so a
# path segment like ``neon-tools`` (``neon`` followed by ``-``) is NOT a match.
# Anchoring here — rather than a bare substring — is what keeps quoted mentions
# (``echo "neon branches delete"``) and path arguments from false-positiving.
# ---------------------------------------------------------------------------
_SEP = r"(?:^|[\n;&|(`])\s*"  # start-of-line, separator, or substitution opener
_ASSIGN = r"(?:\w+=\S+\s+)*"  # a leading run of ``VAR=value`` env assignments
_PATH = r"(?:[^\s;&|()`]*/)?"  # optional absolute/relative path prefix
_BIN = r"(?P<bin>neonctl|neon)"  # the invoked binary token (longer alt first)
_END = r"(?=\s|$|[;&|`)])"  # binary token must end at ws / end / separator
# ``args`` runs up to the next shell separator / substitution boundary.
_ARGS = r"(?P<args>[^\n;&|`)]*)"

_NEON_INVOCATION = re.compile(_SEP + _ASSIGN + _PATH + _BIN + _END + _ARGS)

# ---------------------------------------------------------------------------
# The read-only allowlist. Noun -> the read verbs permitted under it. Nouns are
# alias-normalized first. ``me`` is a verbless read command handled specially.
# The noun names are constants so the allowlist and the alias map share one
# source of truth. ``list``/``get`` are the only read-only actions.
# ---------------------------------------------------------------------------
_PROJECTS = "projects"
_BRANCHES = "branches"
_DATABASES = "databases"
_ROLES = "roles"
_OPERATIONS = "operations"

_LIST_GET = frozenset({"list", "get"})
_LIST_ONLY = frozenset({"list"})

_ALLOWED: dict[str, frozenset[str]] = {
    _PROJECTS: _LIST_GET,
    _BRANCHES: _LIST_GET,
    _DATABASES: _LIST_ONLY,
    _ROLES: _LIST_ONLY,
    _OPERATIONS: _LIST_GET,
}

# The CLI's own singular / short aliases for each managed noun.
_NOUN_ALIASES: dict[str, str] = {
    "project": _PROJECTS,
    "branch": _BRANCHES,
    "database": _DATABASES,
    "db": _DATABASES,
    "role": _ROLES,
    "operation": _OPERATIONS,
}

# Flag-only invocations that are read-only (bare ``neon``, version, help). Help
# is also detected anywhere in the args (it short-circuits execution in the
# yargs-based CLI, so ``neon branches delete --help`` only prints help).
_READONLY_FLAGS = frozenset({"--version", "-V", "--help", "-h"})
_HELP_FLAGS = frozenset({"--help", "-h"})


def _has_credential_flag(flags: list[str]) -> bool:
    """True if any flag reveals credentials (``--reveal`` / a password flag)."""
    for flag in flags:
        low = flag.lower()
        if low.startswith("--reveal") or "password" in low:
            return True
    return False


def _classify_positionals(positionals: list[str]) -> str | None:
    """Deny reason for the positional noun/verb tokens, or None if read-only.

    A mutating verb can never occupy the read-verb slot while producing an
    actual mutation, so requiring an allowlisted (noun, verb) pair here is what
    makes false-DENY — never false-ALLOW — the only failure mode.
    """
    noun = _NOUN_ALIASES.get(positionals[0], positionals[0])
    if noun == "me":
        return None
    if noun not in _ALLOWED:
        return f"'{positionals[0]}' is not a read-only neon subcommand (deny-by-default)"
    verb = positionals[1] if len(positionals) > 1 else None
    if verb in _ALLOWED[noun]:
        return None
    subcmd = f"{positionals[0]} {verb}".strip() if verb else positionals[0]
    return f"'{subcmd}' is not a read-only neon subcommand (deny-by-default)"


def _deny_reason(args: str) -> str | None:
    """Return a deny reason for one neon invocation's args, or None if allowed.

    ``args`` is everything after the binary token, up to the next shell
    separator. The classification is allowlist / deny-by-default: only the
    read-only shapes return None; every other shape returns a human-readable
    reason.
    """
    tokens = args.split()
    # ``--help`` / ``-h`` anywhere short-circuits to help output — read-only.
    if any(tok in _HELP_FLAGS for tok in tokens):
        return None
    flags = [tok for tok in tokens if tok.startswith("-")]
    positionals = [tok for tok in tokens if not tok.startswith("-")]
    # Credential-revealing flags are never allowed, whatever the subcommand.
    if _has_credential_flag(flags):
        return "reveals database credentials (connection string / password)"
    if not positionals:
        # Bare ``neon`` (prints usage) or a version/no-op flag form.
        if all(flag in _READONLY_FLAGS for flag in flags):
            return None
        return "is not a read-only neon invocation (deny-by-default)"
    return _classify_positionals(positionals)


def find_denied(command: str) -> tuple[str, str] | None:
    """Return (blocked_segment, reason) for the first denied neon invocation.

    Scans EVERY neon/neonctl invocation at a command position in ``command``.
    If any is disallowed the whole command is denied — chaining cannot smuggle a
    destructive call past an allowed one. Returns None if there is no neon
    invocation, or every one is read-only.
    """
    for match in _NEON_INVOCATION.finditer(command):
        reason = _deny_reason(match.group("args"))
        if reason is not None:
            segment = f"{match.group('bin')} {match.group('args')}".strip()
            return (segment, reason)
    return None


def _deny_message(segment: str, reason: str, command: str) -> str:
    """Operator-facing hard-block explanation surfaced with the deny decision."""
    return (
        "NEON — read-only for agents (Nathan-law 2026-07-03)\n\n"
        f"Command: {command.strip()}\n"
        f"Blocked segment: {segment}\n"
        f"Reason: This {reason}.\n\n"
        "Agents get READ-ONLY Neon access; every mutating, destructive, or "
        "credential-revealing Neon operation is operator-only — the estate has "
        "a history of accidental full-database wipes. Allowed: neon me / "
        "--version / --help, projects list|get, branches list|get, databases "
        "list, roles list, operations list|get.\n\n"
        "To run this yourself, invoke it directly in your session:\n"
        f"    ! {segment}"
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

    denied = find_denied(command)
    if denied is None:
        return 0
    segment, reason = denied
    _emit_deny(_deny_message(segment, reason, command))
    return 0  # _emit_deny exits; unreachable, kept for type clarity


if __name__ == "__main__":
    sys.exit(main())
