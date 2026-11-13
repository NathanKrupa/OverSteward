# ABOUTME: Tests guard_endless_substitution — refuse a process substitution that never ends (OS#723).
# ABOUTME: The fixtures that make it fire are the point; so are the ones that must not.

"""`read -t 5 < <(:; exec cat /dev/zero >/dev/null)` leaks one spinning process per call.

`read` gives up after five seconds and the shell closes its end of the pipe, but
`cat /dev/zero >/dev/null` never touches that pipe, so nothing ever tells it to
stop. A dispatch agent used the shape as a sleep substitute in a loop on
2026-11-12; 115 `cat` processes were spinning, laptop load was about 127, and an
AG `make verify` took 59 minutes before another agent found them.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "hooks" / "guard_endless_substitution.py"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"

#: Verbatim from OS#723.
ISSUE_COMMAND = "read -t 5 < <(:; exec cat /dev/zero >/dev/null)"

#: The refusal's own words, so a crash on stderr can never pass for a refusal.
REFUSAL = "BLOCKED — a process substitution that never ends"


def _load():
    path = REPO_ROOT / "shared" / "scripts" / "dev" / "guard_endless_substitution.py"
    spec = importlib.util.spec_from_file_location("guard_endless_substitution", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load()


BLOCKED = [
    ISSUE_COMMAND,
    "read -t 5 < <(exec cat /dev/zero)",
    "until [ -f done ]; do read -t 5 < <(:; exec cat /dev/zero >/dev/null); done",
    "read -t 5 <(cat /dev/zero)",
    "read -t 5 < <(cat < /dev/zero)",
    "read -t 5 < <(exec 3</dev/zero; cat <&3)",
    "read -t 5 < <(dd if=/dev/zero of=/dev/null)",
    "read -t 5 < <(cat /dev/urandom > /dev/null)",
    "read -t 5 < <(exec yes > /dev/null)",
    "read -t 5 < <(sleep infinity)",
    "read -t 5 < <(tail -f /dev/null)",
    "read -t 5 < <(tail -F build.log)",
    "read -t 5 < <(tail --follow=name build.log)",
    "tee >(cat /dev/zero > /dev/null) < in.txt",
    # A head with no byte count never finds a newline in a stream of zeros.
    "read -t 5 < <(head -n 1 /dev/zero)",
    # Nested: the inner substitution is still a substitution.
    "diff <(sort <(yes)) other.txt",
    # Active inside double quotes only through a command substitution.
    'x="$(cat <(yes))"',
    "cd /tmp && read -t 5 < <(:; exec cat /dev/zero >/dev/null)",
    # An escaped quote opens no string, so it cannot hide the substitution after it.
    "echo \\' <(yes)",
    'echo "a\\"b" <(yes)',
    # A `#` inside a word starts no comment.
    "echo issue#723 <(yes)",
    # A subshell inside the substitution does not close it.
    "read -t 5 < <( (true); exec cat /dev/zero )",
    # A newline separates commands inside the body too.
    "read -t 5 < <(:\nyes)",
    # A `<<-` heredoc ends at its tab-indented delimiter, not at the end of the text.
    "cat <<-EOF > notes.md\n\tprose\n\tEOF\nread -t 5 < <(yes)",
    # A leading assignment does not hide the command it prefixes.
    "read -t 5 < <(X=1 yes)",
    # A body whose quotes do not balance is still read.
    "read -t 5 < <(yes 'x)",
]

ALLOWED = [
    # The pin: a plain timed read with no substitution.
    "read -t 5",
    "read -t 5 line",
    "read -r -t 5 -p 'continue? ' answer",
    # The sanctioned waits.
    "until [ -f /tmp/done ]; do sleep 5; done",
    "timeout 300 tail --pid=4242 -f /dev/null",
    # Process substitutions that end.
    "diff <(sort a.txt) <(sort b.txt)",
    "read -t 5 < <(:)",
    "read -t 5 <> <(:)",
    "comm -12 <(git ls-files) <(ls)",
    "cat <(head -c 16 /dev/urandom)",
    "cat <(head -c 1024 /dev/zero)",
    "cat <(head -n 1 /dev/urandom)",
    "cat <(dd if=/dev/zero bs=1 count=8 2>/dev/null)",
    "cat <(yes | head -3)",
    "cat <(timeout 5 tail -f build.log)",
    "cat <(timeout 5 cat /dev/zero)",
    # A redirect stays in its stage, so the head that bounds it is the one reading it.
    "cat <(head -c 5 < /dev/zero)",
    "cat <(tail -f --pid=4242 build.log)",
    # Never-ending readers outside any substitution are not this guard's business.
    "cat /dev/zero | head -c 10",
    "yes | head -3",
    "dd if=/dev/zero of=img bs=1M count=8",
    "tail -f build.log",
    # Prose about the rule is not an invocation (OS#401).
    "gh issue comment 723 --body 'never write read -t 5 < <(exec cat /dev/zero)'",
    'git commit -m "docs: forbid read -t 5 < <(exec cat /dev/zero)"',
    "echo '<(yes)'",
    "echo \\<\\(yes\\)",
    "ls # read -t 5 < <(cat /dev/zero)",
    "cat <<'EOF'\nread -t 5 < <(exec cat /dev/zero)\nEOF",
    "cat <<-EOF > notes.md\n\tread -t 5 < <(yes)\n\tEOF\ndiff <(sort a) <(sort b)",
]


class TestBlocked:
    @pytest.mark.parametrize("command", BLOCKED)
    def test_an_endless_substitution_is_refused(self, guard, command):
        assert guard.endless_substitutions(command), command


class TestAllowed:
    @pytest.mark.parametrize("command", ALLOWED)
    def test_an_ordinary_command_is_not_refused(self, guard, command):
        assert not guard.endless_substitutions(command), command

    def test_the_allowed_list_is_not_trivially_satisfied(self, guard):
        """A guard that never fires would pass every ALLOWED case."""
        assert all(guard.endless_substitutions(c) for c in BLOCKED)

    def test_a_heredoc_does_not_hide_the_command_after_it(self, guard):
        command = "cat <<'EOF' > notes.md\nprose\nEOF\nread -t 5 < <(exec cat /dev/zero)"
        assert guard.endless_substitutions(command)


class TestUnbalanced:
    def test_an_unclosed_substitution_is_evaluated_rather_than_waved_through(self, guard):
        # A guard's safe direction is to look harder, not to give up.
        assert guard.endless_substitutions("read -t 5 < <(exec cat /dev/zero")


def _run(hook: Path, command: str, tool: str = "Bash", env_extra=None):
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"tool_name": tool, "tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(REPO_ROOT), **(env_extra or {})},
        cwd=REPO_ROOT,
    )


class TestHookProtocol:
    def test_the_issue_command_is_refused_with_the_reason_and_the_sanctioned_waits(self):
        result = _run(HOOK, ISSUE_COMMAND)
        assert result.returncode == 2
        assert REFUSAL in result.stderr
        assert "Traceback" not in result.stderr
        for sanctioned in ("run_in_background", "Monitor", "timeout N tail --pid"):
            assert sanctioned in result.stderr, sanctioned
        assert "cat /dev/zero" in result.stderr, "the refusal must name what it refused"

    def test_a_plain_timed_read_exits_zero_silently(self):
        result = _run(HOOK, "read -t 5")
        assert result.returncode == 0
        assert result.stderr == ""

    def test_a_non_bash_tool_is_ignored(self):
        result = _run(HOOK, ISSUE_COMMAND, tool="Read")
        assert result.returncode == 0

    def test_unparseable_input_does_not_block(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)], input="not json",
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0

    def test_the_environment_override_is_honoured(self):
        result = _run(
            HOOK, ISSUE_COMMAND, env_extra={"CLAUDE_ALLOW_ENDLESS_SUBSTITUTION": "1"}
        )
        assert result.returncode == 0


_HOOK_SCRIPT = re.compile(r"\.claude/hooks/([A-Za-z0-9_]+\.py)")


def _registered_bash_hooks() -> list[Path]:
    """Every PreToolUse hook this repo's settings run before a Bash call."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    scripts = []
    for entry in settings["hooks"]["PreToolUse"]:
        if entry.get("matcher") != "Bash":
            continue
        for hook in entry["hooks"]:
            scripts.extend(_HOOK_SCRIPT.findall(hook["command"]))
    return [REPO_ROOT / ".claude" / "hooks" / script for script in scripts]


class TestOverrideValue:
    def test_an_override_other_than_one_does_not_disarm_the_guard(self):
        result = _run(
            HOOK, ISSUE_COMMAND, env_extra={"CLAUDE_ALLOW_ENDLESS_SUBSTITUTION": "0"}
        )
        assert result.returncode == 2
        assert REFUSAL in result.stderr


class TestRegisteredHookSet:
    """Against what actually runs, not against the module: this is the red OS#723 asks for."""

    def test_the_registered_set_is_not_empty(self):
        assert _registered_bash_hooks()

    def test_the_registered_hooks_refuse_the_issue_command(self):
        refusals = [
            hook.name
            for hook in _registered_bash_hooks()
            if (result := _run(hook, ISSUE_COMMAND)).returncode == 2
            and REFUSAL in result.stderr
        ]
        assert refusals == ["guard_endless_substitution.py"]

    def test_the_registered_hooks_let_a_plain_timed_read_through(self):
        blocked = [
            hook.name
            for hook in _registered_bash_hooks()
            if _run(hook, "read -t 5").returncode != 0
        ]
        assert blocked == []
