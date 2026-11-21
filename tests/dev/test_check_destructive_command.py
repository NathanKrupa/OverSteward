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


def test_quoted_separator_char_is_not_a_command(hook):
    """A separator inside quotes is text the shell hands on as one argument.

    The command is lexed rather than pattern-matched, so a quoted ``;`` or
    ``(`` stays inside its token instead of opening a command position. The
    assertions are inverted from the regex era, when the anchor recognised a
    command position rather than a *shell-parsed* one and this cost was
    accepted. It is the shape that hard-denied an operator's issue body
    (OS#402), so it is no longer acceptable.
    """
    assert hook._match('echo "; rm -rf /"') is None
    assert hook._match('echo "(rm -rf /tmp)"') is None


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
# Lexed argv — a command counts only where the shell would run it, and a flag
# counts only where the shell would pass it (OS#402). Every fixture below was
# run individually against the pre-tokenising hook and seen red there.
# ---------------------------------------------------------------------------

# The exact shape from OS#402: a `gh issue comment` whose heredoc BODY merely
# documents dangerous commands. Nothing runs, or could run — the verbs are prose
# inside a quoted command substitution. The old raw scan answered `deny` on it,
# which an operator cannot approve past.
_HEREDOC_BODY_DOCUMENTING_COMMANDS = (
    'gh issue comment 1 --body "$(cat <<\'EOF\'\n'
    "Do not run these in the primary checkout:\n"
    "\n"
    "rm -rf /some/tree\n"
    "git rebase -i main\n"
    "git commit --no-verify\n"
    "EOF\n"
    ')"'
)


def test_heredoc_body_documenting_commands_is_not_an_evasion(hook):
    """Red before: the body's `--no-verify` produced a hard deny."""
    assert hook._match_hook_evasion(_HEREDOC_BODY_DOCUMENTING_COMMANDS) is None


def test_heredoc_body_documenting_commands_is_not_destructive(hook):
    """Red before: the body's `rm -rf` produced an ask."""
    assert hook._match(_HEREDOC_BODY_DOCUMENTING_COMMANDS) is None


def test_heredoc_body_documenting_commands_emits_no_decision():
    """End to end — the operator's `gh issue comment` must produce no output."""
    proc = _run_hook(_payload(_BASH, _HEREDOC_BODY_DOCUMENTING_COMMANDS))
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_quoted_bypass_flag_is_still_a_flag(hook):
    """Red before: quoting the flag hid it from the raw scan entirely."""
    result = hook._match_hook_evasion('git commit -m msg "--no-verify"')
    assert result is not None
    assert result[0] == _NO_VERIFY


def test_quoted_bypass_flag_denies_end_to_end():
    proc = _run_hook(_payload(_BASH, 'git commit -m msg "--no-verify"'))
    assert proc.returncode == 0
    assert _hso(proc)[_DECISION] == _DENY


def test_quoted_destructive_flag_is_still_a_flag(hook):
    """Red before: `rm "-rf" /important/tree` deleted a tree unprompted."""
    result = hook._match('rm "-rf" /important/tree')
    assert result is not None
    assert result[0] == _RM_RF


def test_quoted_destructive_flag_asks_end_to_end():
    proc = _run_hook(_payload(_BASH, 'rm "-rf" /important/tree'))
    assert proc.returncode == 0
    assert _hso(proc)[_DECISION] == _ASK


@pytest.mark.parametrize(
    "cmd",
    [
        # A message, a PR body, a doc line — the flag is one word of an
        # argument, never an argument.
        "git commit -m 'stop passing --no-verify to git'",
        'gh pr create --body "never merge with --admin"',
        'printf "%s\\n" "git add -A"',
        # The red ones: a shell separator *inside* the quoted argument used to
        # open a command position, so the message text denied itself.
        "git commit -m 'commit; git commit --no-verify'",
        'gh pr create --body "steps: (git add -A) then push"',
    ],
)
def test_evasion_flag_inside_an_argument_is_not_an_invocation(hook, cmd):
    assert hook._match_hook_evasion(cmd) is None


def test_unlexable_evasion_still_denies(hook):
    """An unbalanced quote cannot be lexed — err toward refusing, never allowing."""
    assert hook._match_hook_evasion('git commit --no-verify -m "unclosed') is not None


def test_unlexable_destructive_still_asks(hook):
    assert hook._match('rm -rf /important/tree "unclosed') is not None


def test_unlexable_input_decides_end_to_end():
    proc = _run_hook(_payload(_BASH, 'git commit --no-verify -m "unclosed'))
    assert proc.returncode == 0
    assert _hso(proc)[_DECISION] == _DENY


# ---------------------------------------------------------------------------
# Red team — evasion shapes the raw scan missed, closed by reading argv.
# Each was run individually against the pre-tokenising hook and seen red.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cmd", "expected_category"),
    [
        # A wrapper word in front of git: the shell still runs git.
        ("env git commit --no-verify -m x", _NO_VERIFY),
        ("command git commit --no-verify -m x", _NO_VERIFY),
        ("exec git commit --no-verify -m x", _NO_VERIFY),
        ("env FOO=1 git commit --no-verify -m x", _NO_VERIFY),
        ("env -u GIT_DIR git commit --no-verify -m x", _NO_VERIFY),
        ("env git add -A", _ADD_ALL),
        # A config override before the verb.
        ("git -c user.name=x commit --no-verify -m y", _NO_VERIFY),
        ("git -c core.hooksPath=/dev/null commit", _HOOKSPATH),
        # Text a shell is told to execute is a command, not a quoted mention.
        ("bash -c 'git commit --no-verify -m x'", _NO_VERIFY),
        ('sh -c "git add -A"', _ADD_ALL),
        # An absolute path is still the same program.
        ("/usr/bin/git commit --no-verify -m x", _NO_VERIFY),
    ],
)
def test_red_team_evasion_shapes_are_denied(hook, cmd, expected_category):
    result = hook._match_hook_evasion(cmd)
    assert result is not None, f"expected an evasion match for {cmd!r}"
    assert result[0] == expected_category


@pytest.mark.parametrize(
    ("cmd", "expected_category"),
    [
        ("env rm -rf /important/tree", _RM_RF),
        ("sudo rm -rf /important/tree", _RM_RF),
        ("sudo -u nathan rm -rf /important/tree", _RM_RF),
        ("bash -c 'rm -rf /important/tree'", _RM_RF),
        ("/bin/rm -rf /important/tree", _RM_RF),
        ("rm --recursive --force /important/tree", _RM_RF),
        ("/usr/bin/git reset --hard HEAD~3", _RESET_HARD),
    ],
)
def test_red_team_destructive_shapes_still_ask(hook, cmd, expected_category):
    result = hook._match(cmd)
    assert result is not None, f"expected a match for {cmd!r}"
    assert result[0] == expected_category


def test_wrapper_stripping_does_not_invent_a_command(hook):
    """A wrapper in front of a benign command stays benign."""
    assert hook._match("env DEBUG=1 pytest tests/") is None
    assert hook._match_hook_evasion("env git status") is None


# ---------------------------------------------------------------------------
# A read of core.hooksPath is not a change to it (OS#780). Each pass fixture
# denied on the hook before this change; each deny fixture is pinned against
# the mutant named in its test's docstring.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        # A bare read.
        "git config core.hooksPath",
        "git config --get core.hooksPath",
        # A read with company.
        "git config core.hooksPath; ls .githooks",
        "hp=$(git config core.hooksPath || echo .git/hooks)",
        # A separator character inside a quoted word, or after a closing quote,
        # is no separator token read from quoted text.
        'git config core.hooksPath; grep -n "marker\\|docs" .githooks/pre-push',
        "gh api repos/o/r/pulls --jq '.[].number'; git config core.hooksPath",
        # The read grammar's edges.
        "git -C /home/natha/repo config --local --get core.hooksPath",
        "git config get core.hooksPath",
        "git config --show-origin core.hooksPath",
        "git config CORE.HOOKSPATH",
        "sh -c 'git config --get core.hooksPath'",
        # A variable whose name merely ends in PATH redefines nothing.
        "PYTHONPATH=src git config core.hooksPath",
    ],
)
def test_hookspath_read_passes(hook, cmd):
    """Denied before OS#780: a read named the key with nothing after it."""
    assert hook._match_hook_evasion(cmd) is None


def _assert_hookspath_denied(hook, cmd: str) -> None:
    result = hook._match_hook_evasion(cmd)
    assert result is not None, f"expected a deny for {cmd!r}"
    assert result[0] == _HOOKSPATH


@pytest.mark.parametrize(
    "cmd",
    [
        "git config --unset core.hooksPath",
        "git config --unset-all core.hooksPath",
        "git config unset core.hooksPath",
        "git config --global --unset core.hooksPath",
        "git config --unset CORE.HOOKSPATH",
    ],
)
def test_hookspath_unset_still_denies(hook, cmd):
    """Mutant: the key standing last makes a read, the other tokens unchecked."""
    _assert_hookspath_denied(hook, cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "git config core.hooksPath /dev/null",
        "git config --local core.hooksPath ''",
        "git config set core.hooksPath /dev/null",
        "git config --add core.hooksPath /dev/null",
        "git config --replace-all core.hooksPath ''",
    ],
)
def test_hookspath_value_still_denies(hook, cmd):
    """Mutant: a read decided from the tokens before the key, its place unchecked."""
    _assert_hookspath_denied(hook, cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "git config --add core.hooksPath",
        "git config --replace-all core.hooksPath",
        "git config --get --unset-all core.hooksPath",
    ],
)
def test_hookspath_write_flag_still_denies(hook, cmd):
    """Mutant: any read option present makes a read."""
    _assert_hookspath_denied(hook, cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "git config -f .git/config core.hooksPath",
        "git config --edit core.hooksPath",
        "git config >out.txt core.hooksPath",
        "git -c other.key=v config core.hooksPath",
        "git -C -x config core.hooksPath",
        # A subcommand other than config, which an alias could expand to a write.
        "git myalias core.hooksPath",
    ],
)
def test_hookspath_unknown_token_still_denies(hook, cmd):
    """Mutant: tokens the read grammar does not name are skipped."""
    _assert_hookspath_denied(hook, cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        # A value in backticks, bare and inside double quotes.
        "git config core.hooksPath `echo /dev/null`",
        'git config core.hooksPath "`echo /dev/null`"',
        # A brace standing alone.
        "git config core.hooksPath }",
        "git config core.hooksPath {",
        # Each again inside a script handed to a shell.
        "sh -c 'git config core.hooksPath `echo /dev/null`'",
        "sh -c 'git config core.hooksPath \"`echo /dev/null`\"'",
        "sh -c 'git config core.hooksPath }'",
    ],
)
def test_hookspath_backtick_and_brace_still_deny(hook, cmd):
    """Mutant: the backtick and lone-brace checks dropped."""
    _assert_hookspath_denied(hook, cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        # A separator quoted or escaped is a word to the shell.
        'git config core.hooksPath ";"',
        "git config core.hooksPath '|'",
        "git config core.hooksPath \\;",
        "git config core.hooksPath \\{",
        "sh -c 'git config core.hooksPath \";\"'",
    ],
)
def test_hookspath_quoted_separator_still_denies(hook, cmd):
    """Mutant: the quoted-or-escaped separator check dropped."""
    _assert_hookspath_denied(hook, cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "git config core.hooksPath \r/srv/hooks",
        "git config core.hooksPath \x1c/srv/hooks",
        "git config core.hooksPath \u2028/srv/hooks",
    ],
)
def test_hookspath_foreign_line_break_still_denies(hook, cmd):
    """Mutant: the check for line breaks other than a newline dropped."""
    _assert_hookspath_denied(hook, cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        # The array's words run where it is expanded, with what follows there.
        'a=(git config core.hooksPath) ; "${a[@]}" /dev/null',
        'a=(git config core.hooksPath)\n"${a[@]}" /dev/null',
        'v=/dev/null; a=(git config core.hooksPath) ; "${a[@]}" "$v"',
        "declare -a a=(git config core.hooksPath) && \"${a[@]}\" ''",
        'a+=(git config core.hooksPath) ; "${a[@]}" /dev/null',
    ],
)
def test_hookspath_array_assignment_still_denies(hook, cmd):
    """Mutant: the array-assignment check dropped."""
    _assert_hookspath_denied(hook, cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        # An expansion in the -C operand can become several words: other
        # options, another subcommand.
        "d='/r -c core.hooksPath=/dev/null commit -m x'; git -C $d config core.hooksPath",
        "git -C $REPO config core.hooksPath",
        'git -C "$REPO" config core.hooksPath',
        "git -C /r{,x} config core.hooksPath",
        "git -C /r* config core.hooksPath",
        "git -C /r?[ab] config core.hooksPath",
        "git -C ~/repo config core.hooksPath",
    ],
)
def test_hookspath_expanding_dir_still_denies(hook, cmd):
    """Mutant: the shell-expansion check on the -C operand dropped."""
    _assert_hookspath_denied(hook, cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        # Each can make the word git run something other than git.
        "shopt -s expand_aliases\nalias git=gitx\ngit config core.hooksPath",
        "git() ( command git commit -m x ) ; git config core.hooksPath",
        "hash -p /tmp/x/git git; git config core.hooksPath",
        "enable -n command; git config core.hooksPath",
        "PATH=/tmp/x:$PATH; git config core.hooksPath",
        "PATH=/tmp/x git config core.hooksPath",
        "export PATH=/tmp/x:$PATH; git config core.hooksPath",
        "GIT_EXEC_PATH=/tmp/x git config core.hooksPath",
        ". ./defs.sh; git config core.hooksPath",
        "source defs.sh; git config core.hooksPath",
        'eval "$setup"; git config core.hooksPath',
        "trap 'git commit -m x' EXIT; git config core.hooksPath",
        "BASH_ENV=defs.sh bash -c 'git config core.hooksPath'",
    ],
)
def test_hookspath_read_beside_a_redefinition_still_denies(hook, cmd):
    """Mutant: the check for what can redefine git dropped."""
    _assert_hookspath_denied(hook, cmd)


@pytest.mark.parametrize(
    ("cmd", "expected_category"),
    [
        ("git config core.hooksPath || git config core.hooksPath /dev/null", _HOOKSPATH),
        ("git config core.hooksPath && git commit --no-verify -m x", _NO_VERIFY),
    ],
)
def test_hookspath_read_does_not_clear_its_neighbours(hook, cmd, expected_category):
    """Mutant: a read anywhere returns no evasion for the whole command."""
    result = hook._match_hook_evasion(cmd)
    assert result is not None
    assert result[0] == expected_category


def test_hookspath_hash_inside_a_word_does_not_hide_a_later_write(hook):
    """Mutant: ``_lex`` on plain ``shlex.shlex``, which reads ``a#b`` as a comment."""
    _assert_hookspath_denied(
        hook, "git config core.hooksPath; echo a#b; git config core.hooksPath /dev/null"
    )


@pytest.mark.parametrize(
    "cmd",
    [
        'git config core.hooksPath "',
        'echo "x; git config core.hooksPath',
        "sh -c 'git config core.hooksPath \"'",
    ],
)
def test_hookspath_read_in_unlexable_text_still_denies(hook, cmd):
    """Mutant: the read carve-out applied to the quote-stripping fallback."""
    _assert_hookspath_denied(hook, cmd)


def test_hookspath_unset_denies_end_to_end():
    """Both outcomes exit 0, so the decision and its pattern are what is asserted."""
    proc = _run_hook(_payload(_BASH, "git config --unset core.hooksPath"))
    assert proc.returncode == 0
    assert proc.stdout, "expected a deny decision on stdout, got none"
    hso = _hso(proc)
    assert hso[_DECISION] == _DENY
    assert f"Pattern: {_HOOKSPATH}" in hso[_REASON]


def test_hookspath_read_passes_end_to_end():
    proc = _run_hook(_payload(_BASH, "git config core.hooksPath"))
    assert proc.returncode == 0
    assert proc.stdout == ""


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
