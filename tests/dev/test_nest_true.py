# ABOUTME: The nest-true scanner lets the unchanged shell lexer pair quotes nested in a substitution
# ABOUTME: inside a double-quoted string as bash does, and vouches for nothing it does not model.

"""``_nest_true`` against bash, the oracle.

Inside a double-quoted string the shell opens a fresh quoting context in
``$( )``, backticks and ``${ }``. ``_ShellLexer`` toggles on every double
quote, so it closes the outer string at the first inner one. ``_nest_true``
returns the text with each double quote inside such a nested region escaped,
which the unchanged lexer reads as a literal quote, or None when the text holds
a construct it does not model. Every guard carrying ``_ShellLexer`` carries the
scanner too; ``tests/dev/test_hook_lexer_drift.py`` compares the copies.

Bash reads each fixture through ``printf '%s\\0'`` in a temporary directory,
with a ``PATH`` holding only ``cat``, so the only commands the fixtures can run
are the ``echo``, ``printf`` and ``cat`` they are built from. Every data word is
a marker, ``@<n>@``, which bash prints where the lexer keeps its source text;
a word of each reading is compared by the markers it holds, in order.
"""

from __future__ import annotations

import ast
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.dev import test_lexer_comment_rule as comment_rule

DEV = comment_rule.DEV
TESTS = Path(__file__).resolve().parent
_STEMS = (
    "check_destructive_command",
    "guard_main_worktree",
    "guard_promote_cadence",
    "guard_promote_ci_red",
    "guard_shared_venv",
    "guard_trunk_pull",
    "guard_gate_pipe",
    "guard_endless_substitution",
)
GUARDS = {stem: comment_rule._load(stem) for stem in _STEMS}
# The lexer and its line-true reading, as the six-guard block carries them.
block = GUARDS["check_destructive_command"]
gate_pipe = GUARDS["guard_gate_pipe"]
nest_true = block._nest_true
_MARKER = re.compile(r"@\d+@")


def _markers(word: str) -> list[str]:
    return _MARKER.findall(word)


def _bash(text: str, root: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    """Bash run on ``printf '%s\\0' <text>`` in ``root``, ``cat`` the only command on PATH."""
    work = root / "work"
    bin_dir = root / "bin"
    if not work.is_dir():
        work.mkdir()
        bin_dir.mkdir()
        (bin_dir / "cat").symlink_to(shutil.which("cat"))
    script = work / "words.sh"
    script.write_text("unset U\nprintf '%s\\0' " + text + "\n", encoding="utf-8")
    return subprocess.run(
        [shutil.which("bash"), "--norc", "--noprofile", *flags, str(script)],
        cwd=work,
        env={"PATH": str(bin_dir), "LC_ALL": "C"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _bash_words(text: str, root: Path) -> list[str] | None:
    """The words bash makes of ``text`` as arguments, or None unless it ran cleanly."""
    proc = _bash(text, root)
    if proc.returncode != 0 or proc.stderr:
        return None
    return proc.stdout.split("\0")[:-1]


# Bash's parse of ``text``: "ok"; "unclosed", a quote, substitution, expansion
# or heredoc left open, which is the scanner's own business; or "grammar", a
# token where the grammar allows none, which the scanner does not model.
_UNCLOSED = ("unexpected EOF", "unexpected end of file", "delimited by end-of-file")


def _bash_parse(text: str, root: Path) -> str:
    proc = _bash(text, root, "-n")
    if any(message in proc.stderr for message in _UNCLOSED):
        return "unclosed"
    return "ok" if proc.returncode == 0 and not proc.stderr else "grammar"


def _assert_as_bash_reads_it(text: str, root: Path) -> list[str]:
    """``text`` is vouched for, and the lexer's words on it are bash's words."""
    rewritten = nest_true(text)
    assert rewritten is not None, "no vouch"
    words = block._lex(rewritten)
    assert words is not None, "the lexer rejects the nest-true text"
    expected = _bash_words(text, root)
    assert expected is not None, "bash rejected the fixture"
    assert [_markers(word) for word in words] == [_markers(word) for word in expected]
    return words


# -- Row 1: the substitution's inner quoted pair -----------------------------


def test_a_substitution_in_a_double_quoted_string_is_one_word(tmp_path):
    text = '"@1@ $(echo "@2@ @3@") @4@"'
    assert len(block._lex(text)) > 1, "today the lexer splits it"
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert words == ['@1@ $(echo "@2@ @3@") @4@']


# -- Row 2: backticks, and a parameter expansion's default -------------------


@pytest.mark.parametrize(
    "text",
    ['"@1@ `echo "@2@ @3@"` @4@"', '"@1@ ${U:-"@2@ @3@"} @4@"'],
    ids=["backtick", "parameter-default"],
)
def test_the_other_nested_contexts_are_one_word(tmp_path, text):
    assert len(block._lex(text)) > 1, "today the lexer splits it"
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert len(words) == 1


# -- Row 3: quote characters as data in the nested region --------------------


@pytest.mark.parametrize(
    "text",
    [
        "\"@1@ $(echo '@2@ \" @3@') @4@\"",
        '"@1@ $(echo "@2@ \\" @3@") @4@"',
        '"@1@ $(echo "@2@ \\\\") @3@ $(echo "@4@") @5@"',
        "\"@1@ $(echo '@2@ \\\\\" @3@') @4@\"",
        "\"@1@ $(echo '@2@ \\\" @3@') @4@\"",
    ],
    ids=[
        "inside-single-quotes",
        "escaped-quote",
        "escaped-backslash",
        "backslashes-in-single",
        "backslash-in-single",
    ],
)
def test_quote_characters_as_nested_data_keep_the_string_whole(tmp_path, text):
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert len(words) == 1


# -- Row 4: a newline inside the nested quote --------------------------------


def test_a_newline_inside_a_nested_quote_ends_no_command():
    text = 'echo "$(echo "@1@\n@2@")" ; true'
    assert len(block._line_runs(text)) == 2, "today a command end sits at that newline"
    rewritten = nest_true(text)
    assert rewritten is not None, "no vouch"
    runs = block._line_runs(rewritten)
    assert runs == [["echo", '$(echo "@1@\n@2@")', ";", "true"]]


# -- Row 5: the pipe guard's line stream sees the real quote cross its line --


def test_the_pipe_guard_sees_a_real_quote_cross_its_line():
    text = "echo \"$(echo \"it's\")\" '@1@\n@2@' ; true"
    line_end, continuation = gate_pipe._MARKER_CANDIDATES[:2]
    today = gate_pipe._read_lines(text, line_end, continuation)
    assert today.quoted_line_starts == [], "today no line begins inside quotes"
    rewritten = nest_true(text)
    assert rewritten is not None, "no vouch"
    reading = gate_pipe._read_lines(rewritten, line_end, continuation)
    assert not reading.failed
    assert len(reading.quoted_line_starts) == 1


# -- Row 6: deeper nesting, and nesting inside an unquoted substitution ------


def test_two_levels_of_nesting_are_one_word(tmp_path):
    text = '"@1@ $(echo "@2@ $(echo "@3@ @4@") @5@") @6@"'
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert len(words) == 1


def test_a_double_quoted_string_in_an_unquoted_substitution_keeps_its_nesting(tmp_path):
    inner = '"@1@ $(echo "@2@ @3@") @4@"'
    text = f"echo $(printf '%s' {inner})"
    alone = _assert_as_bash_reads_it(inner, tmp_path)
    assert alone[0] not in block._lex(text), "today the inner string is split"
    rewritten = nest_true(text)
    assert rewritten is not None, "no vouch"
    assert alone[0] in block._lex(rewritten)


# -- Row 7: the commit-message shape -----------------------------------------


def test_a_quoted_heredoc_in_a_substitution_is_vouched_and_one_word(tmp_path):
    body = "@1@ it's \"@2@\" (draft) #3\n@3@ (\"x\") 'y'"
    text = f"\"$(cat <<'EOF'\n{body}\nEOF\n)\""
    assert '"@2@"' not in "".join(block._lex(text)), "today it lexes only by dropping quotes"
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert words == [f"$(cat <<'EOF'\n{body}\nEOF\n)"]


def test_a_quoted_heredoc_at_top_level_without_quotes_is_vouched(tmp_path):
    text = "$(cat <<'EOF'\n@1@ (x) #y\nEOF\n)"
    assert nest_true(text) == text


# -- Row 8: parens and comments in a substitution ----------------------------


def test_a_subshell_inside_a_substitution_keeps_its_depth(tmp_path):
    text = '"@1@ $( (echo "@2@ )") ) @3@ $(echo "@4@") @5@"'
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert len(words) == 1


def test_a_comment_inside_a_substitution_is_skipped(tmp_path):
    text = "\"@1@ $(echo \"@2@\" # it's ) \"q\n) @3@ $(echo \"@4@\") @5@\""
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert len(words) == 1


def test_a_hash_inside_a_word_is_not_a_comment(tmp_path):
    text = '"@1@ $(echo @2@#"@3@ )") @4@"'
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert len(words) == 1


def test_a_continued_line_keeps_the_word_start_for_a_comment(tmp_path):
    text = '"@1@ $(echo @2@ \\\n# it\'s ) "q\n) @3@"'
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert len(words) == 1


def test_a_here_string_is_not_a_heredoc():
    assert nest_true('cat <<< "$(echo "a")"') == 'cat <<< "$(echo \\"a\\")"'


def test_a_dollar_before_a_quote_inside_double_quotes_is_data(tmp_path):
    text = "\"@1@ $'@2@\" \"@3@$\""
    assert nest_true(text) == text
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert len(words) == 2


def test_case_is_unmodelled_only_as_a_word_inside_a_substitution():
    text = '"$(echo showcase)" ; case x in x) echo "a";; esac'
    assert nest_true(text) == text


def test_a_tab_stripped_heredoc_ends_at_its_indented_delimiter(tmp_path):
    text = "\"$(cat <<-'EOF'\n\t@1@ \"q\"\n\tEOF\n)\""
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert len(words) == 1


# -- Row 9: no vouch for what the scanner does not model ---------------------


@pytest.mark.parametrize(
    "text",
    [
        'echo "$(echo a',
        "echo $(echo a",
        "x=$(cat <<'E'\nb\nE\n",
        'echo "$(echo "a)',
        "echo \"$(echo $'a')\"",
        "echo \"$(echo $\"a\")\"",
        'cat <(echo "a")',
        'cat >(echo "a")',
        'echo "$((1 + 2))"',
        'echo "$[1 + 2]"',
        'echo "$(case x in x) echo "a";; esac)"',
        'echo "$(cat <<EOF\na\nEOF\n)"',
        "cat <<'EOF'\nit's\nEOF",
        "cat <<'EOF'\na\n",
        "cat <<'EOF'",
        "echo \"$(cat <<'EOF' \"a\nb\"\nEOF\n)\"",
        "echo \"$(cat <<'EOF')\"\nEOF\n",
        "echo \"$(cat <<'A' $(cat <<'B'\nA\nB\n)\n)\"",
        "echo \"$(cat <<'E\nF' a\nE\nF\n)\"",
        "echo \"$(cat <<'E/F'\na\nE/F\n)\"",
        "echo \"$(cat <<'E\\F'\nEF\n)\"",
        "echo \"${U:-'a'}\"",
        'echo "${U:-{a}}"',
        'echo "${U:-a"',
        'echo "`echo \\"a\\"`"',
        'echo "`echo $(echo a)`"',
        "echo \"`cat <<'EOF'\na\nEOF\n`\"",
        "echo \"`echo 'a`'`\"",
        'echo "`echo a',
        "echo 'a",
        'echo "a',
        "echo \"$(cat <<'' \na\n\n)\"",
        "echo " + "\"$(echo " * 70 + "a" + ")\"" * 70,
    ],
    ids=[
        "unclosed-substitution",
        "unclosed-unquoted-substitution",
        "unclosed-unquoted-substitution-after-a-heredoc",
        "unclosed-nested-quote",
        "ansi-c",
        "locale",
        "process-in",
        "process-out",
        "arithmetic",
        "old-arithmetic",
        "case",
        "expanding-heredoc",
        "top-level-heredoc-quote",
        "heredoc-without-delimiter",
        "heredoc-never-begun",
        "heredoc-pending-across-a-quote",
        "heredoc-pending-past-its-frame",
        "heredoc-in-two-frames",
        "heredoc-delimiter-across-lines",
        "heredoc-delimiter-unusual",
        "heredoc-delimiter-backslash-in-quotes",
        "parameter-single-quote",
        "parameter-brace",
        "unclosed-parameter",
        "backtick-escaped-quote",
        "backtick-substitution",
        "backtick-heredoc",
        "backtick-inside-backtick-quote",
        "unclosed-backtick",
        "unclosed-single-quote",
        "unclosed-double-quote",
        "empty-heredoc-delimiter",
        "too-deep",
    ],
)
def test_an_unmodelled_construct_is_not_vouched(text):
    assert nest_true(text) is None


# -- Row 10: text with no nested region comes back byte for byte -------------


def _test_table_texts() -> list[str]:
    names = [
        "test_check_destructive_command.py",
        "test_worktree_guard.py",
        "test_guard_promote_cadence.py",
        "test_guard_promote_ci_red.py",
        "test_guard_shared_venv.py",
        "test_guard_trunk_pull.py",
        "test_guard_gate_pipe.py",
        "test_guard_endless_substitution.py",
        "test_lexer_comment_rule.py",
        "test_lexer_line_ends.py",
        "test_promote_unparsed_text.py",
    ]
    texts = set()
    for name in names:
        tree = ast.parse((TESTS / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                texts.add(node.value)
    return sorted(texts)


def _holds_no_nested_region(text: str) -> bool:
    return '"' not in text or not any(opener in text for opener in ("$(", "`", "${"))


def test_text_with_no_nested_region_comes_back_unchanged():
    candidates = [text for text in _test_table_texts() if _holds_no_nested_region(text)]
    vouched = 0
    for text in candidates:
        result = nest_true(text)
        assert result in (None, text), text
        vouched += result is not None
    # Measured at 1,214 of 1,373; most of the rest is prose holding an apostrophe.
    assert len(candidates) > 1000
    assert vouched > 1000


# -- Row 11: single quotes, and a hash inside the nested quote ---------------


def test_substitution_text_inside_single_quotes_is_untouched(tmp_path):
    text = "'@1@ \"$(echo \"@2@\")\" #x'"
    assert nest_true(text) == text
    _assert_as_bash_reads_it(text, tmp_path)


def test_a_hash_inside_a_nested_quote_is_literal(tmp_path):
    text = '"$(echo "@1@ #x") @2@"'
    assert "@2@" not in "".join(block._lex(text)), "today the hash starts a comment"
    words = _assert_as_bash_reads_it(text, tmp_path)
    assert words == ['$(echo "@1@ #x") @2@']


# -- Row 12: the generated bash differential ---------------------------------


class _Fixtures:
    """Texts built only from the constructs the scanner models, every data word a marker."""

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.count = 0

    def marker(self) -> str:
        self.count += 1
        return f"@{self.count}@"

    def text(self) -> str:
        words = [self.word() for _ in range(self.rng.randint(1, 3))]
        return " ".join(words)

    def word(self) -> str:
        roll = self.rng.random()
        if roll < 0.75:
            return self.double(1)
        if roll < 0.9:
            return "'" + self.marker() + " \"$(x)\" ` #'"
        return self.marker()

    def double(self, depth: int) -> str:
        parts = [self.double_part(depth) for _ in range(self.rng.randint(1, 4))]
        return '"' + "".join(parts) + '"'

    def double_part(self, depth: int) -> str:
        choices = [
            lambda: self.marker() + " ",
            lambda: "' ",
            lambda: " # ",
            lambda: "( ) ",
            lambda: "\\\" ",
            lambda: "\\\\ ",
            lambda: "\n",
        ]
        if depth < 4:
            choices += [lambda: self.substitution(depth)] * 4
            choices += [lambda: self.backtick(), lambda: self.parameter(depth)]
        return self.rng.choice(choices)()

    def substitution(self, depth: int) -> str:
        return "$(" + self.command(depth + 1) + ")"

    def command(self, depth: int) -> str:
        roll = self.rng.random()
        if roll < 0.15:
            body = self.marker() + " it's \"q\" (p) #h $(x) \\\\\"\n" + self.marker()
            return "cat <<'EOF'\n" + body + "\nEOF\n"
        if roll < 0.25:
            return " ( echo " + self.arguments(depth) + " ) "
        if roll < 0.35:
            return "echo " + self.arguments(depth) + " # it's ( \"q\n"
        if roll < 0.45:
            return "printf '%s' " + self.arguments(depth)
        return "echo " + self.arguments(depth)

    def arguments(self, depth: int) -> str:
        choices = [
            lambda: self.marker(),
            lambda: "'" + self.marker() + " \" ( #'",
            lambda: self.double(depth),
            lambda: self.double(depth),
        ]
        return " ".join(self.rng.choice(choices)() for _ in range(self.rng.randint(1, 3)))

    def backtick(self) -> str:
        inner = self.rng.choice(
            [self.marker(), '"' + self.marker() + " ' ( #\"", "'" + self.marker() + ' " ( #\'']
        )
        return "`echo " + inner + "` "

    def parameter(self, depth: int) -> str:
        if self.rng.random() < 0.3:
            return "${U:-" + self.marker() + "} "
        return "${U:-" + self.double(depth + 1) + "} "

    def damaged(self, text: str) -> str | None:
        """``text`` with one quoting or grouping character removed, or None if it has none."""
        positions = [index for index, char in enumerate(text) if char in "\"'()`{}"]
        if not positions:
            return None
        index = self.rng.choice(positions)
        return text[:index] + text[index + 1 :]


def test_bash_and_the_lexer_agree_on_every_vouched_text(tmp_path):
    """Every generated text is vouched and read as bash reads it; damaged ones too where
    bash runs them, and none bash finds unclosed is vouched."""
    fixtures = _Fixtures(801)
    texts = [fixtures.text() for _ in range(250)]
    nested = 0
    for text in texts:
        _assert_as_bash_reads_it(text, tmp_path)
        nested += nest_true(text) != text
    assert nested > 150, "the fixtures must mostly hold a nested quote"

    seen = {"unclosed": 0, "grammar": 0, "failed": 0, "compared": 0}
    for text in texts:
        damaged = fixtures.damaged(text)
        if damaged is None:
            continue
        rewritten = nest_true(damaged)
        parse = _bash_parse(damaged, tmp_path)
        if parse != "ok":
            seen[parse] += 1
            assert parse == "grammar" or rewritten is None, "vouched for text bash finds unclosed"
            continue
        expected = _bash_words(damaged, tmp_path)
        if expected is None:
            seen["failed"] += 1
            continue
        if rewritten is not None:
            seen["compared"] += 1
            words = block._lex(rewritten)
            assert words is not None, "the lexer rejects the nest-true text"
            assert [_markers(word) for word in words] == [_markers(word) for word in expected]
    assert seen["unclosed"] > 30 and seen["compared"] > 10, seen


def test_every_guard_copy_gives_the_same_nest_true_text():
    fixtures = _Fixtures(802)
    texts = [fixtures.text() for _ in range(40)]
    for stem, guard in GUARDS.items():
        assert [guard._nest_true(text) for text in texts] == [nest_true(t) for t in texts], stem
