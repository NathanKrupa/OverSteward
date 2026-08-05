# ABOUTME: Tests for the destructive-command confirm-gate hook (.claude/hooks/check_destructive_command.py).
# ABOUTME: Pure detection logic + the ask-decision stdin/stdout contract; no shell side effects.

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REL = Path(".claude") / "hooks" / "check_destructive_command.py"


def _hook_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _REL
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"could not locate {_REL} above {__file__}")


def _load_hook():
    """Load the deployed hook by file path (no package install needed)."""
    path = _hook_path()
    spec = importlib.util.spec_from_file_location("check_destructive_command", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hook():
    return _load_hook()


# ---------------------------------------------------------------------------
# Block-with-ask — one representative command per careful.md category.
# ---------------------------------------------------------------------------


# Category labels reused across several parametrized rows, hoisted to constants
# so the expected-value column has a single source of truth.
_RM_RF = "rm -rf"
_DROP = "DROP/TRUNCATE"
_RESET_HARD = "git reset --hard"
_PUSH_FORCE = "git push --force"
# Hook-evasion category labels (class 1).
_HOOKSPATH = "core.hooksPath disabled"
_ADD_ALL = "git add -A / ."
_ADD_SECRET = "git add of a secret file"
_NO_VERIFY = "git --no-verify"
_ADMIN = "--admin bypass"


@pytest.mark.parametrize(
    ("cmd", "expected_category"),
    [
        # File system
        ("rm -rf /home/natha/project", _RM_RF),
        ("rm -fr src", _RM_RF),
        ("rm -Rf secrets", _RM_RF),
        ("rm -r /etc/somewhere", "rm -r"),
        ("rm *.py", "rm glob"),
        ("shred -u secret.key", "shred/wipe"),
        ("wipe /dev/sdb", "shred/wipe"),
        # Git — hard to reverse
        ("git push --force origin main", _PUSH_FORCE),
        ("git push -f", _PUSH_FORCE),
        ("git reset --hard HEAD~3", _RESET_HARD),
        ("git clean -fd", "git clean -f"),
        ("git clean -fx", "git clean -f"),
        ("git branch -D feature", "git branch -D"),
        ("git checkout -- .", "git checkout/restore ."),
        ("git restore .", "git checkout/restore ."),
        ("git rebase main", "git rebase"),
        # Database
        ("psql -c 'DROP TABLE users'", _DROP),
        ("sqlite3 db.sqlite 'TRUNCATE logs'", _DROP),
        ("psql -c 'DROP DATABASE prod'", _DROP),
        ("psql -c 'DELETE FROM users'", "DELETE without WHERE"),
        ("python manage.py flush", "manage.py flush"),
        # Container / infrastructure
        ("docker system prune -a", "docker system prune -a"),
        ("docker volume rm pgdata", "docker volume rm"),
        ("kubectl delete deployment web", "kubectl delete"),
        # Package management
        ("npm install -g typescript", "npm install -g"),
        ("npm i -g eslint", "npm install -g"),
        ("pip install requests", "pip install outside a venv"),
        ("python -m pip install requests", "pip install outside a venv"),
        # Command substitution is a command position too
        ("`rm -rf /home/natha/project`", _RM_RF),
        ("$(rm -rf /home/natha/project)", _RM_RF),
        ("(rm -rf /home/natha/project)", _RM_RF),
        ("out=$(rm -rf /home/natha/project)", _RM_RF),
        ("`git reset --hard origin/master`", _RESET_HARD),
        ("$(git reset --hard origin/master)", _RESET_HARD),
        ("(git push --force origin main)", _PUSH_FORCE),
        ("`psql -c 'DROP TABLE users'`", _DROP),
    ],
)
def test_destructive_commands_matched(hook, cmd, expected_category):
    result = hook._match(cmd)
    assert result is not None, f"expected a match for {cmd!r}"
    category, risk = result
    assert category == expected_category
    assert risk  # non-empty risk phrase


# ---------------------------------------------------------------------------
# Pass-through — Safe Exceptions and benign commands, one per category.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        # careful.md Safe Exceptions — artifact rm
        "rm -rf node_modules",
        "rm -rf dist",
        "rm -rf build",
        "rm -rf __pycache__",
        "rm -rf .pytest_cache",
        "rm -rf .mypy_cache",
        "rm -rf mypkg.egg-info",
        "rm -rf ./node_modules/",
        "rm -rf node_modules dist build",
        # careful.md Safe Exceptions — git
        "git stash",
        "git stash pop",
        "git branch -d merged-feature",
        "git push --force-with-lease origin feat",
        "docker system prune",
        # Benign / non-destructive
        "git push origin main",
        "git checkout -b feat/x",
        "git checkout main",
        "git restore --staged file.py",
        "DELETE FROM users WHERE id = 1;",
        "uv pip install requests",
        ".venv/bin/pip install requests",
        "pip install --user black",
        "npm install",
        "npm ci",
        "ls -la",
        "git status",
        'echo "rm -rf /"',
        'grep "git checkout" file',
        "git checkout origin/master -- scripts/dev/",
        # a substitution reaching a harmless command stays clean
        "(git status)",
        "echo $(git rev-parse HEAD)",
        "cd $(pwd) && ls",
        # careful.md Safe Exceptions keep passing inside a group: the closing
        # delimiter must not attach to the argument and hide the artifact name
        "(rm -rf node_modules)",
        "`rm -rf dist`",
        "(cd /repo && rm -rf build)",
        "(git stash)",
        "(git branch -d merged-feature)",
        "(docker system prune)",
    ],
)
def test_safe_commands_pass_through(hook, cmd):
    assert hook._match(cmd) is None, f"expected pass-through for {cmd!r}"


# ---------------------------------------------------------------------------
# False-positive guards.
# ---------------------------------------------------------------------------


def test_env_assignment_prefix_does_not_break_detection(hook):
    # A leading VAR=x env assignment must not hide the destructive verb.
    assert hook._match("FOO=bar rm -rf /data") is not None


def test_env_assignment_form_is_not_itself_flagged(hook):
    # `env VAR=val cmd` where cmd is benign stays a pass-through.
    assert hook._match("env DEBUG=1 pytest tests/") is None


def test_quoted_mention_not_flagged(hook):
    # A destructive verb inside a quoted echo/grep argument is inert data.
    assert hook._match("echo 'rm -rf /'") is None
    assert hook._match("grep -r 'DROP TABLE' migrations/") is None
    assert hook._match("printf 'run git reset --hard'") is None


def test_sql_search_without_db_client_passes(hook):
    # Searching source for a SQL keyword is not executing it.
    assert hook._match("grep -rn 'TRUNCATE' src/") is None
    assert hook._match("cat schema.sql | head") is None


def test_sql_with_db_client_still_flagged(hook):
    # A DB client present means the SQL executes — still a prompt.
    assert hook._match("echo 'TRUNCATE foo' | psql") is not None


# ---------------------------------------------------------------------------
# A client inside a substitution is still a client (OS#307).
#
# `_DB_CLIENT` is a suppressor's escape clause, not a detector: when it fails to
# see the client, `_is_sql_data_only` concludes the SQL is being printed and the
# SQL detectors stand down. A miss here does not lose one detection — it inverts
# the verdict on a command the shell is about to run.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "echo $(psql -c 'DROP TABLE grants')",
        "echo `psql -c 'DROP TABLE grants'`",
        "cat $(sqlite3 app.db 'DROP TABLE users')",
        "printf `mysql -e 'TRUNCATE grants'`",
    ],
)
def test_a_client_in_a_substitution_does_not_suppress_the_sql(hook, cmd):
    """The client is *immediately* preceded by the opener — no whitespace.

    That is the whole gap: the old class carried ``\\s``, so anything with a
    space before the client already matched. Only ``$(psql`` and ``` `psql ```
    slipped, which is why the shape has to be written exactly this way to
    regress.
    """
    assert hook._match(cmd) is not None


@pytest.mark.parametrize(
    "cmd",
    [
        "grep -rn 'DROP TABLE' migrations/",
        "cat schema.sql",
        "echo 'TRUNCATE is a SQL keyword'",
        "rg --files-with-matches 'DELETE FROM users;' src/",
    ],
)
def test_genuine_data_only_commands_stay_clean(hook, cmd):
    """The negative controls: widening the class must not start flagging prose.

    Without these in the same run, a `_DB_CLIENT` that matched everything would
    satisfy every assertion above.
    """
    assert hook._match(cmd) is None


def test_egg_info_not_confused_with_arbitrary_name(hook):
    # A non-artifact directory that merely contains 'build' is not safe.
    assert hook._match("rm -rf build_prod_data") is not None


def test_delete_with_where_passes(hook):
    assert hook._match("psql -c 'DELETE FROM users WHERE id = 1'") is None


def test_quoted_substitution_char_is_an_accepted_false_positive(hook):
    """A regex cannot see quotes, so a quoted separator reads as a real one.

    Already true of ``;``/``|``/``&`` before substitution chars were added: the
    anchor recognises a command position, not a *shell-parsed* command position.
    Adding a backtick and ``(`` extends that accepted cost to those two
    characters. The common quoted mentions (``echo "rm -rf /"``) stay clean
    because they carry no separator at all.
    """
    assert hook._match('echo "; rm -rf /"') is not None
    assert hook._match('echo "(rm -rf /tmp)"') is not None


# ---------------------------------------------------------------------------
# Class 1 — hook-evasion / secret-staging (hard ``deny``).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cmd", "expected_category"),
    [
        # Hook / signing / protection bypass
        ("git commit --no-verify -m x", _NO_VERIFY),
        ("git commit -m x --no-verify", _NO_VERIFY),
        ("git commit --no-gpg-sign -m x", "git --no-gpg-sign"),
        ("gh pr merge 12 --admin --merge", _ADMIN),
        ("git merge --admin", _ADMIN),
        ("git -c core.hooksPath=/dev/null commit -m x", _HOOKSPATH),
        ("git config core.hooksPath ''", _HOOKSPATH),
        ('git -c core.hooksPath="" commit', _HOOKSPATH),
        # Blind whole-tree staging
        ("git add -A", _ADD_ALL),
        ("git add --all", _ADD_ALL),
        ("git add .", _ADD_ALL),
        ("git add -A .", _ADD_ALL),
        # Secret-file staging
        ("git add .env", _ADD_SECRET),
        ("git add .env.local", _ADD_SECRET),
        ("git add config/.env.production", _ADD_SECRET),
        ("git add server.pem", _ADD_SECRET),
        ("git add id_rsa.key", _ADD_SECRET),
        ("git add credentials.json", _ADD_SECRET),
        ("git add secrets/credentials", _ADD_SECRET),
        # Class 1 is the non-downgradable tier — command substitution must not
        # walk it back to a class-2 ask, or to no decision at all.
        ("`git commit --no-verify -m x`", _NO_VERIFY),
        ("$(git commit --no-verify -m x)", _NO_VERIFY),
        ("(git commit --no-verify -m x)", _NO_VERIFY),
        ("`gh pr merge 12 --admin --merge`", _ADMIN),
        ("`git add -A`", _ADD_ALL),
        ("$(git add -A)", _ADD_ALL),
        ("(git add -A)", _ADD_ALL),
        ("`git add .env`", _ADD_SECRET),
    ],
)
def test_hook_evasion_matched(hook, cmd, expected_category):
    result = hook._match_hook_evasion(cmd)
    assert result is not None, f"expected an evasion match for {cmd!r}"
    category, reason = result
    assert category == expected_category
    assert reason  # non-empty reason phrase


@pytest.mark.parametrize(
    "cmd",
    [
        # Legitimate explicit-path staging
        "git add src/foo.py",
        "git add tests/",
        "git add tests/dev/test_x.py",
        "git add README.md pyproject.toml",
        # Commit / other git without a bypass flag
        "git commit -m x",
        "git commit -am 'msg'",
        "git config core.hooksPath .githooks",
        # Placeholder dotenv files carry no real values — legitimately committed
        "git add .env.example",
        "git add .env.sample",
        "git add .env.template",
        "git add .env.dist",
        "git add config/.env.example",
        # substitutions that reach no evasion shape stay clean
        "echo $(git rev-parse HEAD)",
        "(git add src/foo.py)",
        "`git status`",
    ],
)
def test_hook_evasion_pass_through(hook, cmd):
    assert hook._match_hook_evasion(cmd) is None, f"expected pass-through for {cmd!r}"


def test_placeholder_dotenv_not_staged_as_secret(hook):
    # The carve-out lives in the secret-staging predicate specifically.
    assert hook._stages_secret_file("git add .env.example") is False
    assert hook._stages_secret_file("git add .env") is True


def test_evasion_wins_over_destructive(hook):
    # A command that is BOTH evasion-class and destructive-class must deny
    # (evasion), never soften to ask. `git add .` leads, a destructive rm
    # follows; evasion must win.
    assert hook._match_hook_evasion("git add . && rm -rf /data") is not None


# ---------------------------------------------------------------------------
# stdin/stdout contract — the ask decision and the tool_name gate.
# ---------------------------------------------------------------------------


_TOOL = "tool_name"
_INPUT = "tool_input"
_CMD = "command"
_BASH = "Bash"
_HSO = "hookSpecificOutput"
_DECISION = "permissionDecision"
_DENY = "deny"
_ASK = "ask"
_REASON = "permissionDecisionReason"


def _payload(tool: str, cmd: str) -> dict:
    return {_TOOL: tool, _INPUT: {_CMD: cmd}}


def _hso(proc: subprocess.CompletedProcess) -> dict:
    """The hookSpecificOutput block from a hook's stdout."""
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


def test_ask_decision_emitted_on_match():
    proc = _run_hook(_payload(_BASH, "rm -rf /home/natha/x"))
    assert proc.returncode == 0
    hso = _hso(proc)
    assert hso["hookEventName"] == "PreToolUse"
    assert hso[_DECISION] == _ASK
    assert "rm -rf" in hso[_REASON]


def test_deny_decision_emitted_on_evasion():
    proc = _run_hook(_payload(_BASH, "git commit --no-verify -m x"))
    assert proc.returncode == 0
    hso = _hso(proc)
    assert hso["hookEventName"] == "PreToolUse"
    assert hso[_DECISION] == _DENY
    assert "I-3" in hso[_REASON]


@pytest.mark.parametrize(
    "cmd",
    [
        "`git commit --no-verify -m x`",
        "$(git commit --no-verify -m x)",
        "(git commit --no-verify -m x)",
        "`git add -A`",
        "(git add -A)",
    ],
)
def test_deny_decision_survives_command_substitution(cmd):
    """Class 1 through a substitution is still a deny — not an ask, not silence."""
    proc = _run_hook(_payload(_BASH, cmd))
    assert proc.returncode == 0
    assert _hso(proc)[_DECISION] == _DENY


@pytest.mark.parametrize(
    "cmd",
    [
        "`rm -rf /home/natha/x`",
        "$(git reset --hard origin/master)",
        "(rm -rf /home/natha/x)",
    ],
)
def test_ask_decision_survives_command_substitution(cmd):
    proc = _run_hook(_payload(_BASH, cmd))
    assert proc.returncode == 0
    assert _hso(proc)[_DECISION] == _ASK


def test_evasion_denies_even_when_destructive_present():
    # `git add .` (evasion) precedes `rm -rf` (destructive/ask). The decision
    # must be deny, proving class-1 is checked first end-to-end.
    proc = _run_hook(_payload(_BASH, "git add . && rm -rf /data"))
    assert proc.returncode == 0
    assert _hso(proc)[_DECISION] == _DENY


def test_safe_command_no_output(hook):
    proc = _run_hook(_payload(_BASH, "rm -rf node_modules"))
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_non_bash_tool_ignored():
    proc = _run_hook(_payload("Edit", "rm -rf /"))
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_unparseable_stdin_does_not_block():
    proc = _run_stdin("not json")
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_empty_command_ignored():
    proc = _run_hook(_payload(_BASH, ""))
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
    canonical = repo_root / "shared" / "scripts" / "dev" / "check_destructive_command.py"
    assert canonical.read_bytes() == deployed.read_bytes()
