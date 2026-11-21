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


GF = "pytest -q | tail -5"
X = "echo hi"


def _refused(command):
    return guard.should_block(command)


class TestOwnLinePipeline:
    """A pipeline refused alone is refused on its own line, whatever the other lines hold."""

    @pytest.fixture(autouse=True)
    def _no_session_override(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_ALLOW_GATE_PIPE", raising=False)

    def test_the_refused_pipeline_is_refused_alone(self):
        assert _refused(GF)

    def test_a_pipeline_after_another_command_line(self):
        assert _refused(f"{X}\n{GF}")

    def test_a_pipeline_before_another_command_line(self):
        """A pin: the first line's pipeline was refused before the change."""
        assert _refused(f"{GF}\n{X}")

    def test_a_crlf_line_end_ends_the_line(self):
        assert _refused(f"{X}\r\n{GF}\r\n")

    def test_a_line_ending_in_an_even_run_of_backslashes_is_not_continued(self):
        assert _refused("echo a\\\\\n" + GF)

    def test_a_trailing_comment_ends_at_its_own_line(self):
        assert _refused(f"{X} # note\n{GF}")

    def test_a_comment_ending_in_a_backslash_does_not_continue(self):
        assert _refused(f"{X} # note \\\n{GF}")

    def test_a_comment_ending_in_a_pipe_character_does_not_continue(self):
        assert _refused(f"{X} # note |\n{GF}")

    def test_a_reserved_word_ending_its_line(self):
        assert _refused(f"if true; then\n{GF}\nfi")

    def test_a_pipeline_after_an_unbalanced_quote(self):
        assert _refused(f"echo 'unclosed\n{GF}")

    def test_a_last_line_pipeline_holding_its_own_unbalanced_quote(self):
        """Refused alone through the unlexable fallback; no line begins inside its quote."""
        line = "pytest -q 'x | tail -5"
        assert _refused(line)
        assert _refused(f"{X}\n{line}")

    def test_a_pipeline_before_a_lone_trailing_backslash(self):
        assert _refused(f"{X}\n{GF}\\")
        assert _refused(f"{X}\n{GF}\n\\")

    def test_a_pipeline_after_an_and_operator_ending_its_line(self):
        """A pin: an AND operator was a separator before the change."""
        assert _refused(f"true &&\n{GF}")

    def test_a_pipeline_inside_multi_line_groups(self):
        """A pin: an opening parenthesis or brace was a separator before the change."""
        assert _refused(f"(\n{GF}\n)")
        assert _refused(f"{{\n{GF}\n}}")
        assert _refused(f"x=$(\n{GF}\n)")
        assert _refused(f"case $x in\na) {GF} ;;\nesac")


class TestContinuedPipeline:
    """A pipeline the shell continues across lines is read as one pipeline."""

    @pytest.fixture(autouse=True)
    def _no_session_override(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_ALLOW_GATE_PIPE", raising=False)

    def test_a_gate_ending_its_line_with_a_pipe(self):
        assert _refused(f"{X}\npytest -q |\ntail -5")

    def test_a_gate_ending_its_line_with_a_stderr_pipe(self):
        assert _refused(f"{X}\npytest -q |&\ntail -5")

    def test_a_gate_ending_in_a_line_continuation_after_another_line(self):
        assert _refused(f"{X}\npytest -q \\\n| tail -5")

    def test_a_gate_ending_in_a_line_continuation_alone(self):
        assert _refused("pytest -q \\\n| tail -5")

    def test_a_gate_whose_name_a_continuation_splits(self):
        assert _refused(f"{X}\npyt\\\nest -q | tail -5")

    def test_a_pipe_then_a_trailing_comment(self):
        assert _refused(f"{X}\npytest -q | # note\ntail -5")

    def test_a_pipe_then_a_comment_only_line(self):
        assert _refused(f"{X}\npytest -q |\n# note\ntail -5")

    def test_a_continued_pipeline_and_a_comment_ending_in_a_pipe(self):
        """Each line end decided on its own: two offenders, not one uniform choice."""
        command = (
            f"{X}\npytest -q | # note\ntail -5\n"
            "echo x # trailing |\npytest -q | head -3"
        )
        found = guard.offending_pipelines(command)
        filters = {pipeline[-1][0] for pipeline in found}
        assert filters == {"tail", "head"}, found

    def test_a_gate_with_a_quoted_lone_newline_argument(self):
        assert _refused("pytest -k '\n' | tail -5")


class TestQuotedSpans:
    """Where the lexer reports a quote spanning lines, the lines are read again."""

    @pytest.fixture(autouse=True)
    def _no_session_override(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_ALLOW_GATE_PIPE", raising=False)

    HEREDOC_ONE = "cat > a.md <<'EOF'\nit's one\nEOF\n"
    HEREDOC_TWO = "\ncat > b.md <<'EOF'\nit's two\nEOF"

    def test_a_pipeline_between_two_heredocs_holding_an_apostrophe(self):
        assert _refused(self.HEREDOC_ONE + GF + self.HEREDOC_TWO)

    def test_an_own_line_pipeline_whose_quoted_argument_starts_a_word_with_a_hash(self):
        """Blanking the quotes would make the hash a comment; the line is lexed afresh."""
        line = 'pytest -q -k "a #b" | tail -5'
        assert _refused(line)
        assert _refused(self.HEREDOC_ONE + line + self.HEREDOC_TWO)

    def test_a_fresh_line_is_read_to_its_end_and_across_a_waiting_pipe(self):
        line = 'echo hi; pytest -q -k "a #b" |\ntail -5'
        assert _refused(line)
        assert _refused(self.HEREDOC_ONE + line + self.HEREDOC_TWO)

    def test_a_fresh_line_stops_at_its_own_end(self):
        """A pipe on the next line must not become the fresh line's last stage."""
        line = 'pytest -q -k "a #b" | tail -5\necho x | grep y'
        assert _refused(self.HEREDOC_ONE + line + self.HEREDOC_TWO)

    def test_the_blanked_reading_blanks_double_quotes_too(self):
        """A double quote the lexer mis-tracks, in text that lexes, before a pipeline."""
        command = "echo \"$(echo 'say \"hi')\"; pytest -q | tail -5\ncat <<'EOF'\nit's\nEOF"
        assert guard._lex(command) is not None, "the text must lex, or today's degrade reads it"
        assert _refused(command)

    def test_a_line_after_a_continuation_inside_a_quoted_span(self):
        """The heredoc's quote runs on through a comment's backslash, as the lexer reads it."""
        line = 'pytest -q -k "a #b" | tail -5'
        command = "cat > a.md <<'EOF'\nsay \"hi\nEOF\n# see C:\\\n" + line
        assert _refused(command)

    def test_a_pipeline_after_a_quote_mistracked_inside_a_substitution(self):
        """Mid-line, after the mistracked quote: the blanked reading reads it."""
        command = 'echo "$(echo "it\'s")"; pytest -q | tail -5' + self.HEREDOC_TWO
        assert guard._lex(command) is not None, "the text must lex, or today's degrade reads it"
        assert _refused(command)

    def test_a_quoted_multi_line_text_with_a_line_reading_as_a_refused_pipeline(self):
        """The recorded cost of reading quoted spans again: this is refused."""
        assert _refused(f"git commit -m 'one\n{GF}\nthree'")

    def test_quoted_text_without_such_a_line_is_allowed(self):
        assert not _refused("git commit -m 'one\ntwo'\necho done")
        assert not _refused("pytest -k 'a | tail'\necho done")


class TestVouchedCommandKeepsOneLineQuotes:
    """Where ``_nest_true`` vouches for a command, its readings run on the nest-true text alone,
    and the blanked reading blanks only the quotes that text shows crossing a line end, never
    closing, or opening on a line begun inside quotes. Without a vouch, every quote is blanked.

    MQ, a quoted text spanning lines elsewhere in the command, is what brings the
    blanked reading in. A quote that opens and closes on one line then reads as it
    does in a single-line command.
    """

    @pytest.fixture(autouse=True)
    def _no_session_override(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_ALLOW_GATE_PIPE", raising=False)

    MQ = "git commit -m 'one\ntwo'"
    ALTERNATION = "grep -E 'ok|gaudi' log.txt | head -3"
    QUOTED_COMMAND = ".venv/bin/python mut.py f.md 'pytest -q | tail -5'"
    SUBSTITUTION = 'out="$(pytest -q | tail -5)"'
    # The toggle lexer closes the outer string at the first inner quote and pairs
    # the two apostrophes; the shell runs the pipeline between them.
    NESTED = 'echo "$(echo "it\'s")"'
    MISTRACKED_PAIR = f"{NESTED}; pytest -q | tail -5; {NESTED}"
    # An ANSI-C quote, which the scanner does not model: no vouch.
    UNMODELLED = "echo $'z'"

    @staticmethod
    def _vouched(command):
        vouched = guard._nest_true(command)
        assert vouched is not None, "the fixture must be one the scanner vouches for"
        return vouched

    def test_a_quoted_alternation_naming_a_gate_beside_a_multi_line_quote(self):
        for command in (f"{self.MQ}\n{self.ALTERNATION}", f"{self.ALTERNATION}\n{self.MQ}"):
            self._vouched(command)
            assert not _refused(command)

    def test_a_quoted_command_string_passed_as_an_argument_beside_a_multi_line_quote(self):
        command = f"{self.MQ}\n{self.QUOTED_COMMAND}"
        self._vouched(command)
        assert not _refused(command)

    def test_the_same_lines_alone_are_allowed(self):
        """A pin: without a multi-line quote the blanked reading never runs."""
        assert not _refused(self.ALTERNATION)
        assert not _refused(self.QUOTED_COMMAND)

    def test_without_a_vouch_every_quote_is_blanked_as_before(self):
        """The unmodelled line takes the vouch away, and the alternation reads as a pipeline."""
        command = f"{self.MQ}\n{self.ALTERNATION}\n{self.UNMODELLED}"
        assert guard._nest_true(command) is None
        assert _refused(command)

    def test_a_quoted_substitution_reads_as_it_does_alone(self):
        """The stated extent: the shell runs this pipeline, and the guard does not read it alone."""
        assert not _refused(self.SUBSTITUTION)
        assert not _refused(f"{self.MQ}\n{self.SUBSTITUTION}")

    @pytest.mark.parametrize(
        "command",
        [
            MISTRACKED_PAIR,
            f"{MISTRACKED_PAIR}\n{MQ}",
            f"{MQ}\n{MISTRACKED_PAIR}",
            f"{NESTED} 'start\nx' ; pytest -q | tail -5 ; echo 'y'\n{NESTED}",
            f"{MQ}\n{NESTED} 'start\nx' ; pytest -q | tail -5 ; echo 'y' {NESTED}",
            'pytest -k "$(echo "a\nb")" | tail -5',
        ],
    )
    def test_a_pipeline_the_toggle_lexer_misplaces_among_nested_quotes_stays_refused(
        self, command
    ):
        """The constructs the earlier drafts of this change stopped on: the shell runs each
        pipeline, and the nest-true text, read alone, shows it."""
        assert self._vouched(command) != command
        assert _refused(command)

    def test_a_gate_just_after_a_nested_quote_in_a_quote_held_across_lines_stays_refused(self):
        """The backslash the scanner put before the nested quote is blanked with it, so the
        gate's name is a word of its own, as blanking the original text left it."""
        command = 'echo "$(\n"pytest" -q | tail -5)"'
        assert self._vouched(command) != command
        assert _refused(command)

    def test_a_pair_on_a_line_begun_inside_quotes_is_suspect(self):
        """Kept as quoted text, the pair would hide the separator that blanking it shows:
        blanking the crossing quote alone glues the gate on the line to the filter."""
        command = "echo 'a\npytest -q' \"b ; c\" | tail -5"
        self._vouched(command)
        assert not _refused(command)

    def test_a_continued_line_is_still_the_line_begun_inside_quotes(self):
        """Only a line end outside quotes starts a line the lexer can vouch for."""
        command = "echo 'a\npytest -q' x \\\n \"b ; c\" | tail -5"
        self._vouched(command)
        assert not _refused(command)

    def test_a_pattern_inside_a_quote_held_across_lines_stays_refused(self):
        """A pin: a quote that crosses a line end is blanked, so its lines read as code."""
        command = f"git commit -m 'one\n{self.ALTERNATION}\nthree'"
        self._vouched(command)
        assert _refused(command)

    def test_a_double_quoted_pattern_continued_across_a_line_stays_refused(self):
        """A backslash-newline inside double quotes is a line end the quote crossed."""
        command = 'grep -E "ok|gaudi \\\n" log.txt | head -3'
        self._vouched(command)
        assert _refused(command)

    def test_an_escaped_quote_character_outside_quotes_opens_no_span(self):
        """The backslash makes the apostrophe literal; the pair after it still closes on its line."""
        command = f"{self.MQ}\necho it\\'s; {self.ALTERNATION}"
        self._vouched(command)
        assert not _refused(command)

    def test_a_quote_that_never_closes_is_suspect_through_a_character_of_the_other_kind(self):
        """Only the quote's own character closes it, so this one runs to the end of the text."""
        text = "x 'b \"c\nd\" | e"
        reading = guard._read_lines(text, "\x1c", "\x1d")
        assert guard._blank_suspect_quotes(text, reading.quote_spans) == "x  b  c\nd  | e"

    def test_the_whole_suspect_span_is_blanked_through_its_closing_quote(self):
        """Every quote character from the opening through the closing, both kinds."""
        text = "a 'b \"c\nd' x\n\"e\" f"
        reading = guard._read_lines(text, "\x1c", "\x1d")
        assert guard._blank_suspect_quotes(text, reading.quote_spans) == 'a  b  c\nd  x\n"e" f'

    def test_the_backslashes_before_a_blanked_quote_are_blanked_with_it(self):
        text = 'a "\\\\\\"b\nc"'
        reading = guard._read_lines(text, "\x1c", "\x1d")
        assert guard._blank_suspect_quotes(text, reading.quote_spans) == "a      b\nc "


class TestLineReadingKeepsTodaysReading:
    @pytest.fixture(autouse=True)
    def _no_session_override(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_ALLOW_GATE_PIPE", raising=False)

    def test_a_continuation_into_an_indented_gate_is_still_refused(self):
        """Refused before the change, though the shell runs no gate; kept."""
        assert _refused(f"{X} \\\n  {GF}")

    def test_a_filter_pipeline_after_a_gate_line_is_still_refused(self):
        """Refused before the change through the neighbouring line; kept."""
        assert _refused("pytest -q\ncat log.txt | tail -5")

    def test_the_sanctioned_forms_on_separate_lines_are_allowed(self):
        assert not _refused("pytest -q > out.txt 2>&1; rc=$?\ncat out.txt | tail -5")
        assert not _refused("pytest -q | tee out.txt\necho done")

    def test_a_pipe_continued_past_a_heredoc_body_is_outside_this_rule(self):
        """A pin: the guard does not model heredocs, and this is not refused alone either."""
        assert not _refused("pytest -q <<EOF |\nbody\nEOF\ntail -5")


class TestMarkerCharacters:
    @pytest.fixture(autouse=True)
    def _no_session_override(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_ALLOW_GATE_PIPE", raising=False)

    def test_text_holding_one_marker_candidate_is_still_read_by_line(self):
        assert _refused(f"echo \x1e\n{GF}")

    def test_text_holding_every_marker_candidate_is_read_line_by_line(self):
        assert _refused(f"echo \x1c\x1d\x1e\x1f\n{GF}")


class TestLineOverride:
    @pytest.fixture(autouse=True)
    def _no_session_override(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_ALLOW_GATE_PIPE", raising=False)

    def test_the_pipelines_own_prefix_waves_it_through(self):
        assert not _refused(f"{X}\nCLAUDE_ALLOW_GATE_PIPE=1 {GF}")

    def test_an_override_on_another_line_does_not(self):
        assert _refused(f"CLAUDE_ALLOW_GATE_PIPE=1 {X}\n{GF}")


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

    def test_an_own_line_pipeline_exits_two_naming_the_filter_and_the_pipeline(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_ALLOW_GATE_PIPE", raising=False)
        result = self._run({"tool_name": "Bash", "tool_input": {"command": f"{X}\n{GF}"}})
        assert result.returncode == 2
        assert "swallowed by `tail`" in result.stderr
        assert "    pytest -q | tail -5\n" in result.stderr
        assert "Traceback" not in result.stderr

    def test_allowed_multi_line_quoted_text_exits_zero_silently(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_ALLOW_GATE_PIPE", raising=False)
        command = "pytest -k 'a | tail'\necho done"
        result = self._run({"tool_name": "Bash", "tool_input": {"command": command}})
        assert result.returncode == 0
        assert result.stderr == ""

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
