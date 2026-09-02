# ABOUTME: Tests guard_gate_pipe — refuse a gate whose exit status is a filter's (OS#424 rec 2).
# ABOUTME: The fixtures that make it fire are the point; so are the ones that must not.

"""`pytest -q 2>&1 | tail -20` reports **tail's** exit status, which is always 0.

A failing gate therefore reads as a pass. `pr-workflow.md` has prohibited the
shape in prose since 2026-08-21 and it recurred twice anyway — including in AG
PR#1763, whose own trajectory note cites the rule while breaking it. OS#424's
recurrence table is the argument for a hook: prose-enforced rules recur 8+
times, hooked ones 0-2.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "hooks" / "guard_gate_pipe.py"


def _load():
    path = REPO_ROOT / "shared" / "scripts" / "dev" / "guard_gate_pipe.py"
    spec = importlib.util.spec_from_file_location("guard_gate_pipe", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


guard = _load()


BLOCKED = [
    "pytest -q 2>&1 | tail -20",
    "pytest | head",
    "make verify 2>&1 | tail -40",
    "make ci-light | tail -n 30",
    "gaudi check . --severity error --exit-code | tail",
    ".venv/bin/gaudi check src/ | head -50",
    "ruff check . | tail -5",
    "mypy src/ 2>&1 | tail",
    "bandit -r src/ | head -20",
    "uv run pytest -q | tail -20",
    ".venv/bin/python -m pytest tests/ | tail",
    "cd /repo && pytest -q | tail -20",
    "pytest -q | grep FAILED | tail -5",
]

ALLOWED = [
    # No gate in the pipeline.
    "cat verify.log | tail -20",
    "git log --oneline | head -5",
    "tail -f /var/log/syslog",
    # A gate with no filter swallowing its status.
    "pytest -q",
    "make verify",
    "pytest -q > /tmp/out.txt 2>&1",
    "pytest -q | tee /tmp/out.txt",
    # The filter is not in the final position, so the gate's own status can
    # still be read via PIPESTATUS and the sanctioned redirect form is nearby.
    "pytest -q | tail -20 | grep -c FAILED",
    # Prose about the rule must not be refused (OS#401).
    "gh issue comment 1 --body 'never write pytest -q | tail -20'",
    'git commit -m "docs: forbid make verify 2>&1 | tail"',
    "echo 'pytest | tail'",
]


class TestBlocked:
    @pytest.mark.parametrize("command", BLOCKED)
    def test_a_gate_whose_status_a_filter_swallows_is_refused(self, command):
        assert guard.should_block(command), command


class TestAllowed:
    @pytest.mark.parametrize("command", ALLOWED)
    def test_an_ordinary_command_is_not_refused(self, command):
        assert not guard.should_block(command), command

    def test_the_allowed_list_is_not_trivially_satisfied(self):
        """A guard that never fires would pass every ALLOWED case."""
        assert any(guard.should_block(c) for c in BLOCKED)


class TestOverride:
    def test_a_deliberate_one_off_can_be_waved_through_inline(self):
        assert not guard.should_block("CLAUDE_ALLOW_GATE_PIPE=1 pytest -q | tail -20")

    def test_the_override_must_be_this_commands_own_prefix(self):
        # An override on some other command in the line does not license the gate.
        assert guard.should_block(
            "CLAUDE_ALLOW_GATE_PIPE=1 echo hi; pytest -q | tail -20"
        )

    def test_a_quoted_mention_of_the_override_is_not_an_override(self):
        assert guard.should_block("echo 'CLAUDE_ALLOW_GATE_PIPE=1'; pytest -q | tail")


class TestUnlexable:
    def test_an_unbalanced_quote_is_evaluated_rather_than_waved_through(self):
        # A guard's safe direction is to look harder, not to give up.
        assert guard.should_block("pytest -q 'unclosed | tail -20")


class TestHookProtocol:
    def _run(self, payload: dict, env_extra=None):
        import os

        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, **(env_extra or {})},
        )

    def test_a_blocked_command_exits_two_and_explains(self):
        result = self._run({"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}})
        assert result.returncode == 2
        assert "PIPESTATUS" in result.stderr or "redirect" in result.stderr.lower()

    def test_an_allowed_command_exits_zero(self):
        result = self._run({"tool_name": "Bash", "tool_input": {"command": "pytest -q"}})
        assert result.returncode == 0

    def test_a_non_bash_tool_is_ignored(self):
        result = self._run({"tool_name": "Read", "tool_input": {"command": "pytest | tail"}})
        assert result.returncode == 0

    def test_unparseable_input_does_not_block(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)], input="not json",
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0

    def test_the_environment_override_is_honoured(self):
        result = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}},
            env_extra={"CLAUDE_ALLOW_GATE_PIPE": "1"},
        )
        assert result.returncode == 0


class TestDeployment:
    def test_canonical_and_deployed_are_byte_identical(self):
        canonical = REPO_ROOT / "shared" / "scripts" / "dev" / "guard_gate_pipe.py"
        assert canonical.read_bytes() == HOOK.read_bytes()

    def test_the_hook_is_registered_in_settings(self):
        settings = json.loads(
            (REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        rendered = json.dumps(settings)
        assert "guard_gate_pipe.py" in rendered, (
            "the guard exists but nothing invokes it — a hook that is not "
            "registered is a file, not a control"
        )
