# ABOUTME: Tests for the Neon read-only guard hook (.claude/hooks/guard_neon.py).
# ABOUTME: Allowlist / deny-by-default decision logic + the deny stdin/stdout contract.

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REL = Path(".claude") / "hooks" / "guard_neon.py"


def _hook_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _REL
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"could not locate {_REL} above {__file__}")


def _load_hook():
    """Load the deployed hook by file path (no package install needed)."""
    path = _hook_path()
    spec = importlib.util.spec_from_file_location("guard_neon", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    return _load_hook()


# A representative destructive invocation, reused across several rows.
_DELETE = "neon branches delete br-x"


# ---------------------------------------------------------------------------
# Allowlist — read-only neon commands pass (find_denied returns None).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "neon me",
        "neon --version",
        "neon --help",
        "neon -h",
        "neon branches --help",
        "neon branches delete --help",  # help short-circuits execution
        "neon projects list",
        "neon projects get pr-123",
        "neon branches list",
        "neon branches get br-abc",
        "neon branches get br-abc --project-id pr-1",
        "neon databases list",
        "neon roles list",
        "neon operations list",
        "neon operations get op-9",
        "neon",  # bare — prints usage
        # Alias nouns the CLI itself accepts.
        "neon project list",
        "neon branch get br-1",
        "neon db list",
        "neon role list",
        # neonctl covered identically.
        "neonctl me",
        "neonctl branches list",
        # Full-path / relative-path invocations of an allowed command still pass.
        "/home/natha/.local/node/bin/neon me",
        "./neon projects list",
    ],
)
def test_readonly_commands_allowed(hook, cmd):
    assert hook.find_denied(cmd) is None


# ---------------------------------------------------------------------------
# Deny-by-default — mutating / destructive / credential-revealing commands.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        _DELETE,
        "neon branches reset br-x",
        "neon branches restore br-x main",
        "neon branches rename br-x newname",
        "neon branches set-default br-x",
        "neon branches add-compute br-x",
        "neon projects delete pr-1",
        "neon projects create",
        "neon projects update pr-1",
        "neon databases delete mydb",
        "neon databases create",
        "neon roles delete admin",
        "neon roles reset-password admin",
        "neon connection-string",
        "neon cs main",  # alias of connection-string
        "neon sql \"SELECT 1\"",
        "neon psql",
        "neon set-context",
        "neon auth",
        "neon api /projects",
    ],
)
def test_mutating_commands_denied(hook, cmd):
    assert hook.find_denied(cmd) is not None


def test_credential_reveal_flag_denied(hook):
    # A --reveal / password flag is denied whatever the subcommand shape.
    assert hook.find_denied("neon connection-string --reveal") is not None
    assert hook.find_denied("neon roles get admin --reveal-password") is not None


def test_unknown_subcommand_denied_by_default(hook):
    # A subcommand not on the allowlist is blocked without a code change, so a
    # future destructive verb is covered by default.
    assert hook.find_denied("neon buckets nuke everything") is not None
    assert hook.find_denied("neon future-destructive-cmd") is not None
    # A non-read verb under a known noun is likewise denied.
    assert hook.find_denied("neon projects frobnicate pr-1") is not None
    # A bare known noun with no verb is not a read command.
    assert hook.find_denied("neon branches") is not None


# ---------------------------------------------------------------------------
# Chaining / compounding — any disallowed segment blocks the whole command.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        f"neon me && {_DELETE}",
        f"{_DELETE} && neon me",
        "neon me ; neon projects delete pr-1",
        "neon branches list | neon databases delete mydb",
        f"echo hi && {_DELETE}",
        f"X=$({_DELETE})",  # command substitution
        "result=`neon projects delete pr-1`",  # backtick substitution
        "neon me & neon branches reset br-x",  # backgrounding
    ],
)
def test_chained_disallowed_segment_blocks_whole_command(hook, cmd):
    assert hook.find_denied(cmd) is not None


def test_chain_of_only_readonly_allowed(hook):
    assert hook.find_denied("neon me && neon branches list") is None
    assert hook.find_denied("neon projects list | grep main") is None


# ---------------------------------------------------------------------------
# No false-positives on unrelated commands that merely contain "neon".
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "cat /home/natha/neon-notes.txt",
        "cd /opt/neon && ls",
        "grep neon config.yaml",
        "cat file | grep neon",
        'echo "neon branches delete br-x"',  # quoted mention, not an invocation
        'git commit -m "neon branches delete"',
        "ls /usr/lib/neon-tools/",  # neon-tools path, not the binary
        "python neonatal_report.py",  # substring, not a command-position token
    ],
)
def test_unrelated_neon_substrings_not_blocked(hook, cmd):
    assert hook.find_denied(cmd) is None


# ---------------------------------------------------------------------------
# stdin/stdout contract — the deny decision and the tool_name gate.
# ---------------------------------------------------------------------------


_TOOL = "tool_name"
_INPUT = "tool_input"
_CMD = "command"
_BASH = "Bash"
_HSO = "hookSpecificOutput"
_DECISION = "permissionDecision"
_REASON = "permissionDecisionReason"


def _payload(tool: str, cmd: str) -> dict:
    return {_TOOL: tool, _INPUT: {_CMD: cmd}}


def _hso(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout)[_HSO]


def _run_stdin(raw: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_hook_path())],
        input=raw,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    return _run_stdin(json.dumps(payload))


def test_deny_decision_emitted_on_mutating_command():
    proc = _run_hook(_payload(_BASH, _DELETE))
    assert proc.returncode == 0
    hso = _hso(proc)
    assert hso["hookEventName"] == "PreToolUse"
    assert hso[_DECISION] == "deny"
    assert "! neon" in hso[_REASON]


def test_readonly_command_no_output():
    proc = _run_hook(_payload(_BASH, "neon me"))
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_non_bash_tool_ignored():
    proc = _run_hook(_payload("Edit", _DELETE))
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_empty_command_ignored():
    proc = _run_hook(_payload(_BASH, ""))
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_unparseable_stdin_does_not_block():
    proc = _run_stdin("not json")
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Canonical byte-copy treaty — shared/ source and .claude/ deploy must match.
# ---------------------------------------------------------------------------


def test_canonical_and_deployed_copies_are_byte_identical():
    deployed = _hook_path()
    repo_root = next(
        p for p in deployed.resolve().parents if (p / "shared" / "scripts" / "dev").is_dir()
    )
    canonical = repo_root / "shared" / "scripts" / "dev" / "guard_neon.py"
    assert canonical.read_bytes() == deployed.read_bytes()
